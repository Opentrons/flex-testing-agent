#!/usr/bin/env python3
"""RQA-5797 repro: legacy StateSummary missing errorRecoveryCameraEnabled after upgrade.

Product bug: runs persisted on an older build store StateSummary JSON without
``cameraSettings.errorRecoveryCameraEnabled``. After upgrade to Pyro/alpha builds,
``GET /runs`` marks those rows ``ok=false`` with ``InvalidStoredData``.

Repro path (operator-requested):
  1. Downgrade to legacy build (default 9.1.2 external stable)
  2. Upload/analyze/create a run so StateSummary is written on the old schema
  3. Upgrade to target build (default current alpha on robot or 10.0.0-alpha.8)
  4. Scan ``GET /runs`` for ``ok=false`` mentioning errorRecoveryCameraEnabled

Phases can run individually for long installs::

  uv run python scripts/retest_rqa5797.py --phase baseline
  uv run python scripts/retest_rqa5797.py --phase downgrade
  uv run python scripts/retest_rqa5797.py --phase seed
  uv run python scripts/retest_rqa5797.py --phase upgrade
  uv run python scripts/retest_rqa5797.py --phase verify
  uv run python scripts/retest_rqa5797.py --phase all

Full motion repro (operator-requested)::

  uv run python scripts/retest_rqa5797.py --phase repro-v2 --no-skip-if-matches
  uv run python scripts/retest_rqa5797.py --phase play-live
  uv run python scripts/retest_rqa5797.py --phase verify-pre
  uv run python scripts/retest_rqa5797.py --phase snapshot-db
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.install import install_build
from flex_testing_agent.clients.camera import CameraClient
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import Settings, get_settings
from flex_testing_agent.fixtures.auth_settings_suite import default_smoke_protocol_path
from flex_testing_agent.lab_ssh.probe import run_lab_ssh
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
)
from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.robots.flex import FlexRobot
from flex_testing_agent.serial_console import resolve_serial_port, run_command_result
from flex_testing_agent.serial_console.session import SerialSession

ADMIN = "flex_test_admin"
SIGNED_BY = "Flex Harness RQA-5797 Retest"
SMOKE = default_smoke_protocol_path()
LIVE_PROTOCOL = (
    Path(__file__).resolve().parents[1]
    / "docs/test-suggestions/protocols/pyro_live_p50_tip_smoke.py"
)
ROOT = Path(__file__).resolve().parents[1]
ART = Path("artifacts/retest-rqa5797")
STATE_PATH = ART / "state.json"
DB_SNAP_DIR = ART / "db-snapshots"
NEEDLE = "errorRecoveryCameraEnabled"
DEFAULT_LEGACY = "9.1.2"
DEFAULT_TARGET = "10.0.0-alpha.8"


@dataclass
class RunScan:
    label: str
    api_version: str | None
    total_runs: int
    ok_false_count: int
    legacy_failures: list[dict[str, Any]]

    @property
    def bug_reproduced(self) -> bool:
        return bool(self.legacy_failures)


def _run_error_detail(run: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("errorDetails", "errors", "detail", "errorType", "dataError"):
        val = run.get(key)
        if val is not None:
            parts.append(json.dumps(val) if not isinstance(val, str) else val)
    return " ".join(parts)


def _legacy_failures(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for run in runs:
        if run.get("ok") is not False:
            continue
        detail = _run_error_detail(run)
        if (
            NEEDLE in detail
            or "InvalidStoredData" in detail
            or "StateSummary" in detail
        ):
            out.append(
                {
                    "id": run.get("id"),
                    "status": run.get("status"),
                    "detail": detail[:2000],
                }
            )
    return out


async def _api_version(robot: FlexRobot) -> str | None:
    payload = await robot.session.get_json("/health")
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        for key in ("api_version", "robot_system_version", "system_version"):
            val = data.get(key)
            if val:
                return str(val)
    return None


async def access_token_if_crs(settings: Settings) -> str | None:
    """OAuth token when CRS is on; None when access control is disabled."""
    async with FlexRobot(settings) as probe:
        raw = await probe.auth_settings.get_access_control_enabled_raw(
            timeout=settings.robot_health_timeout_seconds
        )
        data = raw.get("data", raw)
        enabled = isinstance(data, dict) and bool(data.get("accessControlEnabled"))
    if not enabled:
        return None
    return await access_token_for_username(settings, ADMIN)


async def scan_runs(settings: Settings, *, label: str) -> RunScan:
    token = await access_token_if_crs(settings)
    async with FlexRobot(settings, access_token=token) as robot:
        version = await _api_version(robot)
        runs = await robot.runs.list_run_summaries()
        legacy = _legacy_failures(runs)
        return RunScan(
            label=label,
            api_version=version,
            total_runs=len(runs),
            ok_false_count=sum(1 for r in runs if r.get("ok") is False),
            legacy_failures=legacy,
        )


async def wait_for_robot(*, timeout_s: float = 1200.0) -> Settings:
    print(f"Waiting for /health (timeout {timeout_s:.0f}s)…")
    deadline = time.monotonic() + timeout_s
    last_error = "not reached"
    while time.monotonic() < deadline:
        try:
            settings = await settings_with_resolved_host(get_settings())
            async with FlexRobot(settings) as robot:
                await robot.session.get_json("/health")
            print(f"Health OK at {settings.robot_host}")
            return settings
        except Exception as exc:
            last_error = str(exc)
            print(f"  poll: {last_error[:160]}")
        await asyncio.sleep(10.0)
    raise TimeoutError(f"Timed out waiting for robot health ({last_error})")


async def install_version(
    settings: Settings,
    version: str,
    *,
    channel: ReleaseChannel,
) -> str | None:
    token = await access_token_if_crs(settings)
    async with FlexRobot(settings, access_token=token) as robot:
        result = await install_build(
            robot,
            version,
            channel=channel,
            download_directory=settings.ensure_artifact_directory() / "downloads",
        )
        print(
            f"Install {version}: succeeded={result.succeeded} "
            f"previous={result.previous_system_version} "
            f"resulting={result.resulting_system_version} detail={result.detail}"
        )
        if not result.succeeded:
            raise RuntimeError(result.detail)
        return result.resulting_system_version


async def resolve_protocol_id(robot: FlexRobot) -> str:
    main_name = SMOKE.name
    for summary in await robot.protocols.list_protocol_summaries():
        files = summary.get("files")
        if not isinstance(files, list):
            continue
        if any(
            isinstance(item, dict)
            and item.get("name") == main_name
            and item.get("role") == "main"
            for item in files
        ):
            pid = summary.get("id")
            if pid:
                return str(pid)
    uploaded = await robot.protocols.upload_protocol(SMOKE)
    data = uploaded.get("data") if isinstance(uploaded, dict) else None
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    raise RuntimeError("could not resolve smoke protocol id")


async def wait_analysis_completed(robot: FlexRobot, protocol_id: str) -> str:
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline:
        analyses = await robot.protocols.list_analyses(protocol_id)
        for item in analyses:
            status = str(item.get("status", "")).lower()
            if status == "completed":
                aid = item.get("id")
                if aid:
                    return str(aid)
            if status in {"failed", "error"}:
                raise RuntimeError(f"analysis failed: {item!r}")
        await asyncio.sleep(2.0)
    raise TimeoutError("analysis did not complete within 180s")


async def seed_legacy_run(settings: Settings) -> dict[str, Any]:
    token = await access_token_if_crs(settings)
    signed_by = SIGNED_BY if token else None
    async with FlexRobot(settings, access_token=token) as robot:
        await ensure_run_state(
            robot,
            DesiredRunState.NO_CURRENT,
            ensure=True,
            capability_name="retest_rqa5797",
            signed_by=signed_by,
        )
        protocol_id = await resolve_protocol_id(robot)
        analysis_id = await wait_analysis_completed(robot, protocol_id)
        created = await robot.runs.create_run(protocol_id=protocol_id)
        data = created.get("data") if isinstance(created, dict) else None
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError(f"create_run missing id: {created!r}")
        run_id = str(data["id"])

        # Touch currentState so StateSummary is persisted on the legacy build.
        with contextlib.suppress(RobotApiError):
            await robot.runs.get_current_state(run_id)

        status = str(data.get("status") or "").lower()
        if status == "idle":
            with contextlib.suppress(RobotApiError):
                await robot.runs.stop(run_id)

        await release_current_run(robot, run_id, signed_by=signed_by)

        return {
            "run_id": run_id,
            "protocol_id": protocol_id,
            "analysis_id": analysis_id,
            "api_version": await _api_version(robot),
        }


async def _wait_run_status(
    robot: FlexRobot,
    run_id: str,
    *,
    wanted: set[str],
    timeout_seconds: float = 600.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last = "unknown"
    while time.monotonic() < deadline:
        payload = await robot.runs.get_run(run_id)
        status = robot.runs.status_from_run(payload) or "unknown"
        last = status
        if status in wanted:
            return status
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for run {run_id} in {wanted}; last={last}")


async def play_live_protocol(settings: Settings) -> dict[str, Any]:
    """Upload/play tip smoke so StateSummary is persisted with real motion."""
    if not LIVE_PROTOCOL.is_file():
        raise FileNotFoundError(LIVE_PROTOCOL)
    token = await access_token_if_crs(settings)
    signed_by = SIGNED_BY if token else None
    async with FlexRobot(settings, access_token=token) as robot:
        await ensure_run_state(
            robot,
            DesiredRunState.NO_CURRENT,
            ensure=True,
            capability_name="retest_rqa5797",
            signed_by=signed_by,
        )
        camera = CameraClient(robot.session)
        status = await camera.get_camera()
        if not bool(status.get("cameraEnabled")):
            status = await camera.set_camera_enabled(camera_enabled=True)
        camera_enabled = bool(status.get("cameraEnabled", True))

        uploaded = await robot.protocols.upload_protocol(LIVE_PROTOCOL)
        protocol_id = robot.protocols.protocol_id_from_upload(uploaded)
        if protocol_id is None:
            raise RuntimeError(f"upload missing protocol id: {uploaded!r}")
        analysis_id = await wait_analysis_completed(robot, protocol_id)
        created = await robot.runs.create_run(protocol_id=protocol_id, timeout=120.0)
        run_id = robot.runs.run_id_from_create(created)
        if run_id is None:
            raise RuntimeError(f"create_run missing id: {created!r}")

        await robot.runs.play(run_id)
        final_status = await _wait_run_status(
            robot,
            run_id,
            wanted={"succeeded", "failed", "stopped"},
            timeout_seconds=900.0,
        )
        commands = await robot.runs.list_commands(run_id)
        cmd_data = commands.get("data")
        command_count = len(cmd_data) if isinstance(cmd_data, list) else 0

        with contextlib.suppress(RobotApiError):
            await robot.runs.get_current_state(run_id)

        await release_current_run(robot, run_id, signed_by=signed_by)

        runs = await robot.runs.list_run_summaries()
        summary = next((r for r in runs if r.get("id") == run_id), {})
        list_ok = summary.get("ok") is not False
        get_payload = await robot.runs.get_run(run_id)
        if isinstance(get_payload, dict):
            get_ok = get_payload.get("ok") is not False
        else:
            get_ok = True

        return {
            "run_id": run_id,
            "protocol_id": protocol_id,
            "analysis_id": analysis_id,
            "final_status": final_status,
            "command_count": command_count,
            "camera_enabled_before_play": camera_enabled,
            "list_ok": list_ok,
            "get_ok": get_ok,
            "api_version": await _api_version(robot),
            "crs_enabled": token is not None,
        }


def _parse_db_export_output(text: str) -> tuple[str, bytes]:
    db_path = ""
    db_size = 0
    chunks: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("DBPATH "):
            db_path = line[len("DBPATH ") :].strip()
        elif line.startswith("DBSIZE "):
            db_size = int(line.split()[1])
        elif line.startswith("DBCHUNK "):
            parts = line.split(" ", 2)
            if len(parts) == 3:
                chunks[int(parts[1])] = parts[2]
    if not db_path or db_size <= 0:
        raise RuntimeError("db export missing DBPATH/DBSIZE markers")
    ordered = "".join(chunks[i] for i in sorted(chunks))
    raw = base64.b64decode(ordered)
    if len(raw) != db_size:
        raise RuntimeError(
            f"db export size mismatch: expected {db_size}, got {len(raw)}"
        )
    return db_path, raw


def _remote_db_export_command() -> str:
    export_script = Path(__file__).resolve().parent / "robot_db_export_on_robot.py"
    payload = base64.b64encode(export_script.read_bytes()).decode("ascii")
    remote = "/tmp/robot_db_export_on_robot.py"
    return f"echo {payload} | base64 -d > {remote} && python3 {remote}"


def pull_db_snapshot_via_ssh(settings: Settings, *, label: str) -> Path:
    """Copy newest on-robot robot_server.db via lab SSH."""
    DB_SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ")
    dest = DB_SNAP_DIR / f"robot_server-{label}-{ts}.db"
    command = _remote_db_export_command()
    print(f"Pulling robot_server.db via SSH ({settings.robot_host})…")
    completed = run_lab_ssh(settings, command, timeout=300.0)
    if completed is None:
        raise RuntimeError("SSH db export did not start (missing ssh binary or key)")
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    log_path = ART / f"ssh-db-pull-{label}.txt"
    ART.mkdir(parents=True, exist_ok=True)
    log_path.write_text(combined)
    if completed.returncode != 0 and "DBDONE" not in combined:
        raise RuntimeError(
            f"SSH db export failed rc={completed.returncode}: {combined[-800:]}"
        )
    db_path, raw = _parse_db_export_output(combined)
    dest.write_bytes(raw)
    print(f"Saved {len(raw)} bytes from {db_path} -> {dest}")
    return dest


def pull_db_snapshot_via_serial(*, label: str) -> Path:
    """Copy newest on-robot robot_server.db via FTDI serial (fallback)."""
    settings = get_settings()
    preferred = (settings.serial_port or "").strip() or None
    device = resolve_serial_port(preferred)
    DB_SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ")
    dest = DB_SNAP_DIR / f"robot_server-{label}-{ts}.db"
    command = _remote_db_export_command()
    print(f"Pulling robot_server.db via serial ({device})…")
    with SerialSession(port=device, baudrate=settings.serial_baud_rate) as session:
        result = run_command_result(session, command, timeout=300.0, login=True)
    log_path = ART / f"serial-db-pull-{label}.txt"
    ART.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.output)
    if "DBDONE" not in result.output:
        raise RuntimeError(
            f"serial db export incomplete: {result.output[-800:]}"
        )
    db_path, raw = _parse_db_export_output(result.output)
    dest.write_bytes(raw)
    print(f"Saved {len(raw)} bytes from {db_path} -> {dest}")
    return dest


def pull_db_snapshot(settings: Settings, *, label: str) -> Path:
    """Prefer SSH; fall back to serial when SSH is unavailable."""
    probe = run_lab_ssh(settings, "true", timeout=15.0)
    if probe is not None and probe.returncode == 0:
        return pull_db_snapshot_via_ssh(settings, label=label)
    print("SSH unavailable; falling back to serial for db snapshot")
    return pull_db_snapshot_via_serial(label=label)


def inspect_local_db_snapshot(
    db_path: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Inspect a pulled robot_server.db for legacy StateSummary rows."""
    out: dict[str, Any] = {"path": str(db_path), "size_bytes": db_path.stat().st_size}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()
    tables = [
        row[0]
        for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    out["tables"] = tables
    run_table = "run" if "run" in tables else ("runs" if "runs" in tables else None)
    if run_table is None:
        out["error"] = "no run table"
        con.close()
        return out
    cols = [row[1] for row in cur.execute(f"PRAGMA table_info({run_table})").fetchall()]
    id_col = "id" if "id" in cols else "run_id"
    has_ss = "state_summary" in cols
    select = (
        f"SELECT {id_col}, state_summary FROM {run_table}"
        if has_ss
        else f"SELECT {id_col} FROM {run_table}"
    )
    rows = cur.execute(select).fetchall()
    out["run_count"] = len(rows)
    legacy_candidates: list[dict[str, str]] = []
    played_row: dict[str, Any] | None = None
    for row in rows:
        rid = str(row[0])
        ss = row[1] if has_ss and len(row) > 1 else None
        if run_id and rid == run_id:
            played_row = {
                "id": rid,
                "has_state_summary": bool(ss),
                "has_camera_settings": bool(ss and "cameraSettings" in ss),
                "has_error_recovery_camera": bool(ss and NEEDLE in ss),
                "preview": (ss or "")[:320],
            }
        if not ss:
            continue
        if "cameraSettings" in ss and NEEDLE not in ss:
            legacy_candidates.append(
                {
                    "id": rid,
                    "reason": "cameraSettings without errorRecoveryCameraEnabled",
                    "preview": ss[:240],
                }
            )
    out["legacy_candidates"] = legacy_candidates[:20]
    out["legacy_candidate_count"] = len(legacy_candidates)
    out["played_run_row"] = played_row
    con.close()
    return out


def load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        raw = json.loads(STATE_PATH.read_text())
        return raw if isinstance(raw, dict) else {}
    return {}


def save_state(state: dict[str, Any]) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def print_scan(scan: RunScan) -> None:
    print(
        f"[{scan.label}] api={scan.api_version} total={scan.total_runs} "
        f"ok_false={scan.ok_false_count} legacy_failures={len(scan.legacy_failures)}"
    )
    for item in scan.legacy_failures[:10]:
        print(json.dumps(item, indent=2))


async def phase_baseline(settings: Settings, state: dict[str, Any]) -> None:
    scan = await scan_runs(settings, label="baseline")
    state["baseline"] = asdict(scan)
    print_scan(scan)


async def phase_downgrade(
    settings: Settings,
    state: dict[str, Any],
    *,
    legacy_version: str,
    channel: ReleaseChannel,
    skip_if_matches: bool,
) -> None:
    token = await access_token_if_crs(settings)
    async with FlexRobot(settings, access_token=token) as robot:
        current = await _api_version(robot)
    state["pre_downgrade_version"] = current
    if skip_if_matches and current and legacy_version in current:
        print(f"Already on {legacy_version}; skipping downgrade")
        state["downgrade_skipped"] = True
        return
    resulting = await install_version(settings, legacy_version, channel=channel)
    state["downgrade"] = {"requested": legacy_version, "resulting": resulting}
    settings = await wait_for_robot()
    post = await scan_runs(settings, label="post-downgrade")
    state["post_downgrade_scan"] = asdict(post)
    print_scan(post)


async def phase_seed(settings: Settings, state: dict[str, Any]) -> None:
    seeded = await seed_legacy_run(settings)
    state["seeded_run"] = seeded
    print("Seeded legacy run:", json.dumps(seeded, indent=2))
    post = await scan_runs(settings, label="post-seed")
    state["post_seed_scan"] = asdict(post)
    print_scan(post)
    seeded_id = seeded["run_id"]
    seeded_ok = next(
        (
            r
            for r in _legacy_failures(await _list_runs(settings))
            if r.get("id") == seeded_id
        ),
        None,
    )
    state["seeded_run_ok_on_legacy"] = seeded_ok is None
    if seeded_ok:
        print("WARNING: seeded run already ok=false on legacy build:", seeded_ok)


async def _list_runs(settings: Settings) -> list[dict[str, Any]]:
    token = await access_token_if_crs(settings)
    async with FlexRobot(settings, access_token=token) as robot:
        return await robot.runs.list_run_summaries()


async def phase_upgrade(
    settings: Settings,
    state: dict[str, Any],
    *,
    target_version: str,
    channel: ReleaseChannel,
    skip_if_matches: bool,
) -> None:
    token = await access_token_if_crs(settings)
    async with FlexRobot(settings, access_token=token) as robot:
        current = await _api_version(robot)
    state["pre_upgrade_version"] = current
    if skip_if_matches and current and target_version in current:
        print(f"Already on {target_version}; skipping upgrade")
        state["upgrade_skipped"] = True
        return
    resulting = await install_version(settings, target_version, channel=channel)
    state["upgrade"] = {"requested": target_version, "resulting": resulting}
    settings = await wait_for_robot(timeout_s=1800.0)
    post = await scan_runs(settings, label="post-upgrade")
    state["post_upgrade_scan"] = asdict(post)
    print_scan(post)


async def phase_play_live(settings: Settings, state: dict[str, Any]) -> None:
    played = await play_live_protocol(settings)
    state["played_run"] = played
    print("Played live run:", json.dumps(played, indent=2))
    if played["final_status"] != "succeeded":
        raise RuntimeError(f"live play did not succeed: {played['final_status']}")
    if not played["list_ok"] or not played["get_ok"]:
        raise RuntimeError("played run not ok on legacy build before upgrade")


async def phase_verify_pre(settings: Settings, state: dict[str, Any]) -> None:
    run_id = (state.get("played_run") or state.get("seeded_run") or {}).get("run_id")
    scan = await scan_runs(settings, label="verify-pre")
    state["verify_pre"] = asdict(scan)
    print_scan(scan)
    if not run_id:
        print("No played/seeded run id in state; skipping per-run checks")
        return
    token = await access_token_if_crs(settings)
    current_state_error: str | None = None
    list_ok = False
    get_ok = False
    status: str | None = None
    async with FlexRobot(settings, access_token=token) as robot:
        get_payload = await robot.runs.get_run(run_id)
        if isinstance(get_payload, dict):
            get_ok = get_payload.get("ok") is not False
        else:
            get_ok = False
        status = robot.runs.status_from_run(get_payload)
        list_row = next(
            (r for r in await robot.runs.list_run_summaries() if r.get("id") == run_id),
            None,
        )
        list_ok = list_row.get("ok") is not False if list_row else False
        if list_row and list_row.get("status"):
            status = str(list_row.get("status"))
        try:
            await robot.runs.get_current_state(run_id)
        except RobotApiError as exc:
            current_state_error = str(exc)
    state["verify_pre_run"] = {
        "run_id": run_id,
        "list_ok": list_ok,
        "get_ok": get_ok,
        "status": status,
        "current_state_error": current_state_error,
    }
    print("Pre-upgrade run check:", json.dumps(state["verify_pre_run"], indent=2))


async def phase_snapshot_db(settings: Settings, state: dict[str, Any]) -> None:
    label = "pre-upgrade"
    dest = pull_db_snapshot(settings, label=label)
    run_id = (state.get("played_run") or state.get("seeded_run") or {}).get("run_id")
    inspection = inspect_local_db_snapshot(dest, run_id=run_id)
    state["db_snapshot"] = {
        "local_path": str(dest),
        "label": label,
        "inspection": inspection,
    }
    print("DB snapshot inspection:", json.dumps(inspection, indent=2))


async def phase_repro_v2(
    settings: Settings,
    state: dict[str, Any],
    *,
    legacy_version: str,
    target_version: str,
    channel: ReleaseChannel,
    skip_if_matches: bool,
) -> bool:
    await phase_downgrade(
        settings,
        state,
        legacy_version=legacy_version,
        channel=channel,
        skip_if_matches=skip_if_matches,
    )
    settings = await wait_for_robot()
    await phase_play_live(settings, state)
    await phase_verify_pre(settings, state)
    settings = await settings_with_resolved_host(get_settings())
    await phase_snapshot_db(settings, state)
    settings = await wait_for_robot(timeout_s=1800.0)
    await phase_upgrade(
        settings,
        state,
        target_version=target_version,
        channel=channel,
        skip_if_matches=skip_if_matches,
    )
    settings = await wait_for_robot(timeout_s=1800.0)
    return await phase_verify(settings, state)


async def phase_verify(settings: Settings, state: dict[str, Any]) -> bool:
    scan = await scan_runs(settings, label="verify")
    state["verify"] = asdict(scan)
    print_scan(scan)
    target_id = (
        (state.get("played_run") or {}).get("run_id")
        or (state.get("seeded_run") or {}).get("run_id")
    )
    target_failure = None
    if target_id:
        for item in scan.legacy_failures:
            if item.get("id") == target_id:
                target_failure = item
                break
        # Also check if run vanished (404 / not in list)
        runs = await _list_runs(settings)
        present = any(r.get("id") == target_id for r in runs)
        state["target_run_present_after_upgrade"] = present
        if not present:
            print(f"WARNING: target run {target_id} not in GET /runs after upgrade")
    state["target_run_failure_after_upgrade"] = target_failure
    reproduced = target_failure is not None or scan.bug_reproduced
    state["bug_reproduced"] = reproduced
    if target_id:
        if target_failure:
            print(f"REPRO: target run {target_id} is ok=false after upgrade")
        elif state.get("target_run_present_after_upgrade"):
            print(f"NO REPRO on target run {target_id} (not in legacy failures)")
    if reproduced:
        print("RQA-5797 repro: legacy StateSummary load failures present")
    else:
        print("RQA-5797 repro: no legacy StateSummary failures detected")
    return reproduced


async def run_phases(args: argparse.Namespace) -> int:
    ART.mkdir(parents=True, exist_ok=True)
    state = load_state()
    channel = ReleaseChannel(args.channel)
    settings = await settings_with_resolved_host(get_settings())

    phases = (
        ["baseline", "downgrade", "seed", "upgrade", "verify"]
        if args.phase == "all"
        else ["repro-v2"]
        if args.phase == "repro-v2"
        else [args.phase]
    )

    reproduced = False
    for phase in phases:
        print(f"\n=== phase {phase} ===")
        if phase == "baseline":
            await phase_baseline(settings, state)
        elif phase == "downgrade":
            settings = await settings_with_resolved_host(get_settings())
            await phase_downgrade(
                settings,
                state,
                legacy_version=args.legacy_version,
                channel=channel,
                skip_if_matches=args.skip_if_matches,
            )
        elif phase == "seed":
            settings = await wait_for_robot()
            await phase_seed(settings, state)
        elif phase == "play-live":
            settings = await wait_for_robot()
            await phase_play_live(settings, state)
        elif phase == "verify-pre":
            settings = await wait_for_robot()
            await phase_verify_pre(settings, state)
        elif phase == "snapshot-db":
            settings = await settings_with_resolved_host(get_settings())
            await phase_snapshot_db(settings, state)
        elif phase == "repro-v2":
            reproduced = await phase_repro_v2(
                settings,
                state,
                legacy_version=args.legacy_version,
                target_version=args.target_version,
                channel=channel,
                skip_if_matches=args.skip_if_matches,
            )
        elif phase == "upgrade":
            settings = await wait_for_robot(timeout_s=1800.0)
            await phase_upgrade(
                settings,
                state,
                target_version=args.target_version,
                channel=channel,
                skip_if_matches=args.skip_if_matches,
            )
        elif phase == "verify":
            settings = await wait_for_robot(timeout_s=1800.0)
            reproduced = await phase_verify(settings, state)
        save_state(state)

    save_state(state)
    print(f"\nState written to {STATE_PATH}")
    if args.phase in {"verify", "all", "repro-v2"}:
        return 1 if reproduced else 0
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=[
            "baseline",
            "downgrade",
            "seed",
            "play-live",
            "verify-pre",
            "snapshot-db",
            "upgrade",
            "verify",
            "repro-v2",
            "all",
        ],
        default="all",
    )
    parser.add_argument("--legacy-version", default=DEFAULT_LEGACY)
    parser.add_argument("--target-version", default=DEFAULT_TARGET)
    parser.add_argument(
        "--channel",
        choices=["external", "internal"],
        default="external",
    )
    parser.add_argument(
        "--skip-if-matches",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip install when robot already reports the requested version",
    )
    args = parser.parse_args()
    return asyncio.run(run_phases(args))


if __name__ == "__main__":
    sys.exit(main())
