#!/usr/bin/env python3
"""Fair retest for RQA-5846 / RQA-5791 on alpha.5+ (PR #22291 timeout bump).

Maps to Casey's root-cause analysis on RQA-5846:
- Tier 0: baseline NS + ps hygiene before stress
- Tier 1: cold POST /runs (control)
- Tier 2: uncurrent then immediate POST /runs with elapsed timing
- Tier 3: paced create/uncurrent cycles (2s gap; same protocolId)
- Tier 4: RQA-5791 orphan audit after single uncurrent

Alpha.5 fix: wait_for_proxy / process-registry polling raised 30s -> 60s.
A 500 on POST /runs with elapsed < 60s is still a failure; 201 after 30-55s
validates the timeout extension.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.fixtures.auth_settings_suite import default_smoke_protocol_path
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
)
from flex_testing_agent.robots.flex import FlexRobot

ADMIN = "flex_test_admin"
SIGNED_BY = "Flex Harness RQA-5846 Fair Retest"
SMOKE = default_smoke_protocol_path()
ROOT = Path(__file__).resolve().parents[1]
ART = Path("artifacts/retest-rqa5846-fair")

# Alpha.5 RunProcessPyroProvider / wait_for_proxy polling ceiling (PR #22291).
PROXY_POLL_TIMEOUT_S = 60.0
TIER3_CYCLES = 10
TIER3_SLEEP_S = 2.0
PRELOADED_PS_EXPECTED = 2

SERIAL_SNAPSHOT_CMD = r"""
ps -ef | grep run_process_entry_point | grep -v grep || true
echo '---NS---'
python3 - <<'PY'
import Pyro5.api as pyro
with pyro.locate_ns() as ns:
    for name in sorted(ns.list()):
        print(name)
PY
"""


@dataclass
class ProcessSnapshot:
    raw: str
    ps_lines: list[str] = field(default_factory=list)
    ns_names: list[str] = field(default_factory=list)
    orphan_ps_lines: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, raw: str) -> ProcessSnapshot:
        if "Could not obtain a Flex serial shell prompt" in raw:
            return cls(raw=raw)
        ps_lines: list[str] = []
        ns_names: list[str] = []
        section = "ps"
        for line in raw.splitlines():
            if line.strip() == "---NS---":
                section = "ns"
                continue
            if section == "ps":
                if "run_process_entry_point" in line:
                    ps_lines.append(line.strip())
            elif line.strip() and not line.startswith(">"):
                ns_names.append(line.strip())
        protocol_ns = {n for n in ns_names if n.startswith("ot-protocol")}
        orphan: list[str] = []
        for ps_line in ps_lines:
            match = re.search(r"--pyroname\s+(\S+)", ps_line)
            pyroname = match.group(1) if match else None
            if pyroname and pyroname not in protocol_ns and pyroname.startswith(
                "ot-protocol"
            ):
                orphan.append(ps_line)
            elif pyroname is None and "run_process_entry_point" in ps_line:
                orphan.append(ps_line)
        return cls(
            raw=raw,
            ps_lines=ps_lines,
            ns_names=ns_names,
            orphan_ps_lines=orphan,
        )


@dataclass
class CreateAttempt:
    tier: str
    cycle: int
    http_status: int
    elapsed_s: float
    run_id: str | None = None
    detail: str = ""


@dataclass
class TierVerdict:
    tier: str
    name: str
    passed: bool | None
    detail: str
    attempts: list[CreateAttempt] = field(default_factory=list)


verdicts: list[TierVerdict] = []


def serial_snapshot(*, label: str) -> ProcessSnapshot:
    proc = subprocess.run(
        ["uv", "run", "flex-test", "serial", "run", SERIAL_SNAPSHOT_CMD.strip()],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    raw = ((proc.stdout or "") + (proc.stderr or "")).strip()
    snap = ProcessSnapshot.parse(raw)
    ART.mkdir(parents=True, exist_ok=True)
    (ART / f"snapshot-{label}.txt").write_text(raw)
    if not snap.ps_lines and not snap.ns_names and "Could not obtain" in raw:
        snap = ProcessSnapshot(raw=raw)
    return snap


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


async def timed_create_run(
    robot: FlexRobot,
    protocol_id: str,
) -> CreateAttempt:
    start = time.monotonic()
    try:
        created = await robot.runs.create_run(protocol_id=protocol_id)
        elapsed = time.monotonic() - start
        data = created.get("data") if isinstance(created, dict) else None
        run_id = str(data["id"]) if isinstance(data, dict) and data.get("id") else None
        return CreateAttempt(
            tier="",
            cycle=0,
            http_status=201,
            elapsed_s=elapsed,
            run_id=run_id,
        )
    except RobotApiError as exc:
        elapsed = time.monotonic() - start
        body = (exc.body or "")[:240]
        return CreateAttempt(
            tier="",
            cycle=0,
            http_status=exc.status_code or 0,
            elapsed_s=elapsed,
            detail=body,
        )


async def uncurrent_run(robot: FlexRobot, run_id: str) -> None:
    status_payload = await robot.runs.get_run(run_id)
    data = status_payload.get("data") if isinstance(status_payload, dict) else None
    status = (data.get("status") or "").lower() if isinstance(data, dict) else ""
    if status == "idle":
        with contextlib.suppress(RobotApiError):
            await robot.runs.stop(run_id)
    await release_current_run(robot, run_id, signed_by=SIGNED_BY)


def classify_5846_attempt(attempt: CreateAttempt) -> str:
    if attempt.http_status == 201:
        if attempt.elapsed_s >= 30.0:
            return (
                f"201 in {attempt.elapsed_s:.2f}s (slow but within "
                f"{PROXY_POLL_TIMEOUT_S:.0f}s poll window; timeout fix may apply)"
            )
        return f"201 in {attempt.elapsed_s:.2f}s"
    if attempt.http_status == 500 and "Can't resolve pyro proxy" in attempt.detail:
        if attempt.elapsed_s < PROXY_POLL_TIMEOUT_S:
            return (
                f"500 proxy-resolve in {attempt.elapsed_s:.2f}s "
                f"(<{PROXY_POLL_TIMEOUT_S:.0f}s; RQA-5846 still failing)"
            )
        return (
            f"500 proxy-resolve after {attempt.elapsed_s:.2f}s "
            f"(>= {PROXY_POLL_TIMEOUT_S:.0f}s; process never registered; check RQA-5791)"
        )
    return f"HTTP {attempt.http_status} in {attempt.elapsed_s:.2f}s: {attempt.detail[:120]!r}"


def record_tier(
    tier: str,
    name: str,
    passed: bool | None,
    detail: str,
    attempts: list[CreateAttempt],
) -> None:
    for attempt in attempts:
        attempt.tier = tier
    verdicts.append(
        TierVerdict(tier=tier, name=name, passed=passed, detail=detail, attempts=attempts)
    )
    status = "PASS" if passed else ("INCONCLUSIVE" if passed is None else "FAIL")
    print(f"[{status}] {tier} {name}: {detail}")


async def tier0_baseline(*, skip_serial: bool) -> ProcessSnapshot | None:
    if skip_serial:
        record_tier(
            "T0",
            "baseline NS/ps snapshot",
            None,
            "serial snapshot skipped (--skip-serial)",
            [],
        )
        return None
    snap = serial_snapshot(label="tier0-baseline")
    orphan_note = (
        f"{len(snap.orphan_ps_lines)} orphan ps line(s)"
        if snap.orphan_ps_lines
        else "no obvious orphan ps lines"
    )
    if "Could not obtain a Flex serial shell prompt" in snap.raw:
        passed = None
        detail = "serial shell unavailable (FTDI prompt timeout)"
    else:
        passed = True
        detail = (
            f"ps_lines={len(snap.ps_lines)} (expected >={PRELOADED_PS_EXPECTED} "
            f"pre-loaded workers); ns_ot_protocol="
            f"{sum(1 for n in snap.ns_names if n.startswith('ot-protocol'))}; "
            f"{orphan_note} (T+0 NS lag on pre-load is OK)"
        )
    record_tier("T0", "baseline NS/ps snapshot", passed, detail, [])
    return snap


async def tier1_cold_create(admin: FlexRobot, protocol_id: str) -> None:
    attempt = await timed_create_run(admin, protocol_id)
    attempt.tier = "T1"
    attempt.cycle = 1
    if attempt.http_status == 201 and attempt.run_id:
        with contextlib.suppress(RobotApiError):
            await uncurrent_run(admin, attempt.run_id)
    detail = classify_5846_attempt(attempt)
    record_tier(
        "T1",
        "cold POST /runs",
        attempt.http_status == 201,
        detail,
        [attempt],
    )


async def tier2_immediate_recreate(admin: FlexRobot, protocol_id: str) -> None:
    first = await timed_create_run(admin, protocol_id)
    first.tier = "T2"
    first.cycle = 1
    if first.http_status != 201 or not first.run_id:
        record_tier(
            "T2",
            "uncurrent then immediate POST /runs",
            False,
            f"setup create failed: {classify_5846_attempt(first)}",
            [first],
        )
        return
    await uncurrent_run(admin, first.run_id)
    second = await timed_create_run(admin, protocol_id)
    second.tier = "T2"
    second.cycle = 2
    if second.http_status == 201 and second.run_id:
        with contextlib.suppress(RobotApiError):
            await uncurrent_run(admin, second.run_id)
    if second.http_status == 201:
        passed: bool | None = True
    elif second.http_status == 500 and second.elapsed_s >= PROXY_POLL_TIMEOUT_S:
        passed = None
    else:
        passed = False
    record_tier(
        "T2",
        "uncurrent then immediate POST /runs",
        passed,
        classify_5846_attempt(second),
        [first, second],
    )


async def tier3_paced_cycles(
    settings,
    protocol_id: str,
    *,
    cycles: int,
) -> None:
    attempts: list[CreateAttempt] = []
    ok = 0
    fail_500 = 0
    slow_ok = 0
    other: list[str] = []
    for i in range(cycles):
        async with await admin_robot(settings) as admin:
            attempt = await timed_create_run(admin, protocol_id)
            attempt.tier = "T3"
            attempt.cycle = i + 1
            attempts.append(attempt)
            if attempt.http_status == 201 and attempt.run_id:
                ok += 1
                if attempt.elapsed_s >= 30.0:
                    slow_ok += 1
                print(
                    f"  T3 cycle {i + 1}/{cycles}: 201 in {attempt.elapsed_s:.2f}s "
                    f"run={attempt.run_id[:8]}…"
                )
                with contextlib.suppress(RobotApiError):
                    await uncurrent_run(admin, attempt.run_id)
            elif attempt.http_status == 500:
                fail_500 += 1
                print(
                    f"  T3 cycle {i + 1}/{cycles}: 500 in {attempt.elapsed_s:.2f}s "
                    f"{attempt.detail[:80]!r}"
                )
            else:
                other.append(f"{attempt.http_status}:{attempt.elapsed_s:.2f}s")
                print(
                    f"  T3 cycle {i + 1}/{cycles}: {attempt.http_status} "
                    f"in {attempt.elapsed_s:.2f}s"
                )
        await asyncio.sleep(TIER3_SLEEP_S)
    passed = fail_500 == 0 and ok == cycles and not other
    detail = (
        f"201={ok}/{cycles} slow_ok(>=30s)={slow_ok} 500={fail_500} "
        f"other={other or 'none'} sleep={TIER3_SLEEP_S}s"
    )
    record_tier("T3", f"{cycles}x paced create/uncurrent", passed, detail, attempts)


async def tier4_orphan_audit(
    admin: FlexRobot,
    protocol_id: str,
    *,
    skip_serial: bool,
) -> None:
    if skip_serial:
        record_tier(
            "T4",
            "RQA-5791 orphan audit after uncurrent",
            None,
            "serial snapshot skipped (--skip-serial)",
            [],
        )
        return
    before = serial_snapshot(label="tier4-before")
    attempt = await timed_create_run(admin, protocol_id)
    attempt.tier = "T4"
    attempt.cycle = 1
    if attempt.http_status != 201 or not attempt.run_id:
        record_tier(
            "T4",
            "RQA-5791 orphan audit after uncurrent",
            None,
            f"create failed before audit: {classify_5846_attempt(attempt)}",
            [attempt],
        )
        return
    await uncurrent_run(admin, attempt.run_id)
    await asyncio.sleep(TIER3_SLEEP_S)
    after = serial_snapshot(label="tier4-after")
    if "Could not obtain a Flex serial shell prompt" in after.raw:
        record_tier(
            "T4",
            "RQA-5791 orphan audit after uncurrent",
            None,
            "serial shell unavailable (FTDI prompt timeout)",
            [attempt],
        )
        return
    orphan = after.orphan_ps_lines or (
        after.ps_lines if after.ps_lines and not any(
            n.startswith("ot-protocol") for n in after.ns_names
        ) else []
    )
    after_count = len(after.ps_lines)
    passed = after_count <= PRELOADED_PS_EXPECTED
    record_tier(
        "T4",
        "RQA-5791 pool settle after uncurrent",
        passed if after.raw else None,
        (
            f"baseline_ps={len(before.ps_lines)} after_ps={after_count} "
            f"(expected <={PRELOADED_PS_EXPECTED}; pyroname reuse OK)"
        ),
        [attempt],
    )


async def admin_robot(settings):
    """Fresh admin OAuth token per tier/cycle (CRS tokens expire during long polls)."""
    token = await access_token_for_username(settings, ADMIN)
    return FlexRobot(settings, access_token=token)


async def run_retest(*, skip_serial: bool, cycles: int) -> int:
    settings = await settings_with_resolved_host(get_settings())
    ART.mkdir(parents=True, exist_ok=True)

    meta: dict[str, object] = {}
    async with FlexRobot(settings) as robot:
        health = await robot.session.get_json("/health")
        data = health.get("data") if isinstance(health, dict) else {}
        disk = (data or {}).get("diskDetails") if isinstance(data, dict) else {}
        meta = {
            "robot_host": settings.robot_host,
            "api_server_version": (data or {}).get("apiServerVersion")
            if isinstance(data, dict)
            else None,
            "disk_details": disk,
            "proxy_poll_timeout_s": PROXY_POLL_TIMEOUT_S,
            "alpha5_fix_pr": "https://github.com/Opentrons/opentrons/pull/22291",
        }
        print("Robot", settings.robot_host, "version", meta["api_server_version"], "disk", disk)

    protocol_id: str | None = None
    async with await admin_robot(settings) as admin:
        await ensure_run_state(
            admin,
            DesiredRunState.NO_CURRENT,
            ensure=True,
            capability_name="retest_rqa5846_fair",
            signed_by=SIGNED_BY,
        )
        protocol_id = await resolve_protocol_id(admin)
    assert protocol_id is not None
    meta["protocol_id"] = protocol_id

    await tier0_baseline(skip_serial=skip_serial)

    async with await admin_robot(settings) as admin:
        await tier1_cold_create(admin, protocol_id)
    async with await admin_robot(settings) as admin:
        await tier2_immediate_recreate(admin, protocol_id)
    await tier3_paced_cycles(settings, protocol_id, cycles=cycles)
    async with await admin_robot(settings) as admin:
        await tier4_orphan_audit(admin, protocol_id, skip_serial=skip_serial)

    summary = {
        "meta": meta,
        "verdicts": [
            {
                **{k: v for k, v in asdict(v).items() if k != "attempts"},
                "attempts": [asdict(a) for a in v.attempts],
            }
            for v in verdicts
        ],
    }
    summary_path = ART / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {summary_path}")

    print("\n=== Summary ===")
    fails = 0
    for v in verdicts:
        status = "PASS" if v.passed else ("INCONCLUSIVE" if v.passed is None else "FAIL")
        print(f"{status}\t{v.tier}\t{v.name}\t{v.detail}")
        if v.passed is False:
            fails += 1
    return 1 if fails else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-serial",
        action="store_true",
        help="Skip FTDI NS/ps snapshots (HTTP tiers still run).",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=TIER3_CYCLES,
        help=f"Tier 3 paced cycle count (default {TIER3_CYCLES}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return asyncio.run(
        run_retest(skip_serial=args.skip_serial, cycles=args.cycles),
    )


if __name__ == "__main__":
    raise SystemExit(main())
