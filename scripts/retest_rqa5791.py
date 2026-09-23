#!/usr/bin/env python3
"""Post-reboot RQA-5791 audit: uncurrent should tear down run-specific subprocesses.

Product keeps ~2 ``run_process_entry_point`` workers pre-loaded at boot (analysis +
runs) so users avoid 20s+ cold-start import latency. Baseline is **not** ps=0.

Repro aligned with Jira RQA-5791:
1. Stable baseline ps + Pyro5 NS (pre-loaded pool, no current run)
2. POST /runs -> confirm run registers in NS + ps
3. Stop idle run if needed, uncurrent
4. ps + NS at checkpoints after uncurrent
5. FAIL if ps count stays above 2 after ~30s settle (pyroname reuse on runs pool is OK)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import Settings, get_settings
from flex_testing_agent.fixtures.auth_settings_suite import default_smoke_protocol_path
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
)
from flex_testing_agent.lab_ssh.probe import run_lab_ssh
from flex_testing_agent.robots.flex import FlexRobot
from flex_testing_agent.serial_console import resolve_serial_port

ADMIN = "flex_test_admin"
SIGNED_BY = "Flex Harness RQA-5791 Retest"
SMOKE = default_smoke_protocol_path()
ROOT = Path(__file__).resolve().parents[1]
ART = Path("artifacts/retest-rqa5791-checkpoints")
DEFAULT_CHECKPOINTS_S = (0.0, 5.0, 30.0, 60.0, 120.0)
EXTENDED_CHECKPOINTS_S = (0.0, 30.0, 60.0, 120.0, 180.0, 300.0, 600.0)
# Product pre-loads analysis + runs workers (see docs/pyro-testing.md).
PRELOADED_PS_EXPECTED = 2
BASELINE_STABLE_DELAY_S = 60.0
SETTLE_WINDOW_S = 30.0  # pool count should be stable by ~30s after uncurrent

# Short one-liner; single-quoted -c avoids serial line-wrap truncation.
SNAPSHOT_CMD = (
    "ps -ef | grep run_process_entry_point | grep -v grep || true; "
    "echo '---NS---'; "
    "python3 -c 'import Pyro5.api as pyro; "
    'ns=pyro.locate_ns(); print("\\n".join(sorted(ns.list())))\''
)


@dataclass
class ProcessSnapshot:
    label: str
    raw: str
    serial_ok: bool
    ps_lines: list[str] = field(default_factory=list)
    ns_names: list[str] = field(default_factory=list)
    protocol_ns: list[str] = field(default_factory=list)
    orphan_ps_lines: list[str] = field(default_factory=list)

    @classmethod
    def from_serial(cls, label: str, raw: str) -> ProcessSnapshot:
        serial_ok = "Could not obtain a Flex serial shell prompt" not in raw
        ps_lines: list[str] = []
        ns_names: list[str] = []
        section = "ps"
        for line in raw.splitlines():
            if line.strip() == "---NS---":
                section = "ns"
                continue
            if (
                section == "ps"
                and "run_process_entry_point" in line
                and "--pyroname" in line
            ):
                ps_lines.append(line.strip())
            elif section == "ns" and line.strip() and not line.startswith(">"):
                ns_names.append(line.strip())
        protocol_ns = [n for n in ns_names if n.startswith("ot-protocol")]
        ns_set = set(ns_names)
        orphan: list[str] = []
        for ps_line in ps_lines:
            match = re.search(r"--pyroname\s+(\S+)", ps_line)
            pyroname = match.group(1) if match else None
            if pyroname and pyroname not in ns_set:
                orphan.append(ps_line)
        return cls(
            label=label,
            raw=raw,
            serial_ok=serial_ok,
            ps_lines=ps_lines,
            ns_names=ns_names,
            protocol_ns=protocol_ns,
            orphan_ps_lines=orphan,
        )

    def summary(self) -> str:
        if not self.serial_ok:
            return "shell unavailable"
        return (
            f"ps={len(self.ps_lines)} protocol_ns={len(self.protocol_ns)} "
            f"orphan_ps={len(self.orphan_ps_lines)}"
        )

    def snapshot_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary(),
            "serial_ok": self.serial_ok,
            "ps_lines": self.ps_lines,
            "ns_names": self.ns_names,
            "protocol_ns": self.protocol_ns,
            "orphan_ps_lines": self.orphan_ps_lines,
            "remaining_ps_count": len(self.ps_lines),
        }


def snapshot_to_dict(snap: ProcessSnapshot) -> dict[str, object]:
    return snap.snapshot_dict()


def pyronames_from_ps_lines(ps_lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in ps_lines:
        match = re.search(r"--pyroname\s+(\S+)", line)
        if match:
            names.add(match.group(1))
    return names


def pyronames_from_snapshot(snap: ProcessSnapshot) -> set[str]:
    return pyronames_from_ps_lines(snap.ps_lines)


def _breakin_serial_shell(ser: object) -> None:
    import serial  # noqa: F401 — type context for callers

    assert hasattr(ser, "write")
    ser.write(b"\x03\x03\x03\n")  # type: ignore[union-attr]
    time.sleep(0.4)
    ser.write(b"\n")  # type: ignore[union-attr]
    time.sleep(0.3)


def reboot_robot() -> None:
    settings = get_settings()
    print("Rebooting KansasFLEX via SSH…")
    completed = run_lab_ssh(settings, "reboot", timeout=30.0)
    if completed is None or completed.returncode not in {0, 255}:
        err = (completed.stderr if completed else "") or (completed.stdout if completed else "")
        print(f"SSH reboot failed ({err[:120]}); falling back to serial…")
        serial_run("reboot", label="reboot")
    print("Waiting 15s for reboot to take effect…")
    time.sleep(15.0)


async def wait_for_robot(*, timeout_s: float = 1200.0) -> str:
    print(f"Waiting for /health (timeout {timeout_s:.0f}s)…")
    deadline = time.monotonic() + timeout_s
    last_error = "not reached"
    while time.monotonic() < deadline:
        try:
            settings = await settings_with_resolved_host(get_settings())
            async with FlexRobot(settings) as robot:
                await robot.session.get_json("/health")
            print(f"Health OK at {settings.robot_host}")
            return settings.robot_host
        except Exception as exc:
            last_error = str(exc)
            print(f"  poll: {last_error[:120]}")
        await asyncio.sleep(10.0)
    raise TimeoutError(f"Timed out waiting for robot health ({last_error})")


def ssh_run(command: str, *, label: str, timeout: float = 60.0) -> str:
    """Run a command on the robot via lab SSH."""
    settings = get_settings()
    completed = run_lab_ssh(settings, command, timeout=timeout)
    if completed is None:
        return "Could not obtain a Flex SSH session (ssh unavailable or timed out)"
    raw = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0 and not raw.strip():
        raw = f"ssh exit {completed.returncode}"
    ART.mkdir(parents=True, exist_ok=True)
    (ART / f"snapshot-{label}.txt").write_text(raw)
    return raw.strip()


def serial_run(command: str, *, label: str) -> str:
    """Run a command on FTDI serial, breaking out of continuation prompts first."""
    import serial  # pyserial via project deps

    settings = get_settings()
    preferred = (settings.serial_port or "").strip() or None
    try:
        device = resolve_serial_port(preferred)
    except Exception as exc:
        return f"Could not obtain a Flex serial shell prompt ({exc})"
    marker = f"__FTA5791_{label}__"
    end = f"{marker}_END"
    script = f"echo {marker}; {command}; echo {end}\n"
    chunks: list[str] = []
    with serial.Serial(device, 115200, timeout=0.5) as ser:
        _breakin_serial_shell(ser)
        ser.write(script.encode())
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            data = ser.read(4096)
            if data:
                chunks.append(data.decode("utf-8", errors="replace"))
                if end in "".join(chunks):
                    break
            else:
                time.sleep(0.1)
    raw = "".join(chunks)
    ART.mkdir(parents=True, exist_ok=True)
    (ART / f"snapshot-{label}.txt").write_text(raw)
    body_match = re.search(
        rf"{re.escape(marker)}\s*(.*?)\s*{re.escape(end)}",
        raw.replace("\r\n", "\n"),
        re.DOTALL,
    )
    return body_match.group(1).strip() if body_match else raw


def process_snapshot(label: str) -> ProcessSnapshot:
    """Capture ps + Pyro NS via SSH (preferred) or FTDI serial fallback."""
    raw = ssh_run(SNAPSHOT_CMD.strip(), label=label)
    if "Could not obtain a Flex SSH session" in raw:
        raw = serial_run(SNAPSHOT_CMD.strip(), label=label)
    if "Could not obtain" in raw and label not in raw:
        raw = f"{raw}\n---NS---\n" if "---NS---" not in raw else raw
    snap = ProcessSnapshot.from_serial(label, raw)
    if not snap.serial_ok and "Could not obtain" not in raw:
        snap = ProcessSnapshot.from_serial(label, raw)
        snap.serial_ok = bool(snap.ps_lines or snap.ns_names or "---NS---" in raw)
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


async def collect_run_state(robot: FlexRobot) -> dict[str, object]:
    from flex_testing_agent.orchestration.run_state import snapshot_run_state

    snap = await snapshot_run_state(robot)
    return {
        "summary": snap.describe(),
        "has_current": snap.has_current,
        "current_run_id": snap.current_run_id,
        "current_status": snap.current_status,
        "run_count": snap.run_count,
    }


async def investigate_post_reboot_baseline(
    settings: Settings,
) -> dict[str, object]:
    """Capture pre-loaded pool baseline after reboot (not ps=0)."""
    investigation: dict[str, object] = {
        "post_health_snapshots": {},
        "preloaded_ps_expected": PRELOADED_PS_EXPECTED,
        "baseline_stable_delay_s": BASELINE_STABLE_DELAY_S,
    }
    admin_token = await access_token_for_username(settings, ADMIN)
    async with FlexRobot(settings, access_token=admin_token) as admin:
        investigation["run_state"] = await collect_run_state(admin)
        runs_payload = await admin.session.get_json("/runs?pageLength=5")
        data = runs_payload.get("data") if isinstance(runs_payload, dict) else None
        investigation["recent_runs"] = data if isinstance(data, list) else []

    for delay in (0.0, 30.0, BASELINE_STABLE_DELAY_S):
        label = f"post-reboot-t{int(delay)}s"
        if delay:
            await asyncio.sleep(delay)
        snap = process_snapshot(label)
        snap_dict = snapshot_to_dict(snap)
        snap_dict["pyronames"] = sorted(pyronames_from_snapshot(snap))
        investigation["post_health_snapshots"][label] = snap_dict

    journal = ssh_run(
        "journalctl -u opentrons-robot-server -b --no-pager -n 40 2>&1 | "
        "grep -Ei 'run_process|protocol|subprocess|current|startup' || true",
        label="post-reboot-journal",
        timeout=30.0,
    )
    investigation["robot_server_journal_excerpt"] = journal[:4000]

    stable = investigation["post_health_snapshots"].get(
        f"post-reboot-t{int(BASELINE_STABLE_DELAY_S)}s"
    )
    t0 = investigation["post_health_snapshots"].get("post-reboot-t0s")
    assert isinstance(stable, dict)
    stable_ps = int(stable.get("remaining_ps_count", 0))
    stable_pyronames = set(stable.get("pyronames", []))
    investigation["stable_pyronames"] = sorted(stable_pyronames)
    investigation["stable_ps_count"] = stable_ps

    run_state = investigation.get("run_state")
    has_current = isinstance(run_state, dict) and bool(run_state.get("has_current"))
    investigation["baseline_clean"] = (
        not has_current and stable_ps >= PRELOADED_PS_EXPECTED
    )
    investigation["baseline_issue"] = None
    if has_current:
        investigation["baseline_issue"] = "current run persisted/restored at boot"
    elif stable_ps < PRELOADED_PS_EXPECTED:
        investigation["baseline_issue"] = (
            f"expected >={PRELOADED_PS_EXPECTED} pre-loaded workers at T+"
            f"{int(BASELINE_STABLE_DELAY_S)}s, saw {stable_ps}"
        )
    elif isinstance(t0, dict):
        t0_orphans = len(t0.get("orphan_ps_lines", []))
        investigation["baseline_note"] = (
            f"T+0 may show {t0_orphans} orphan ps line(s) before NS registers "
            "pre-loaded workers; stable baseline uses T+"
            f"{int(BASELINE_STABLE_DELAY_S)}s."
        )
    else:
        investigation["baseline_note"] = (
            "Pre-loaded analysis + runs workers expected with no current run."
        )
    return investigation


async def run_audit(*, checkpoint_delays_s: tuple[float, ...]) -> dict[str, object]:
    settings = await settings_with_resolved_host(get_settings())
    ART.mkdir(parents=True, exist_ok=True)

    investigation = await investigate_post_reboot_baseline(settings)
    (ART / "baseline-investigation.json").write_text(
        json.dumps(investigation, indent=2),
    )
    print("Baseline investigation:", json.dumps(investigation, indent=2))

    snapshots: dict[str, ProcessSnapshot] = {}
    run_id: str | None = None
    create_elapsed_s: float | None = None
    uncurrent_at: float | None = None

    stable_label = f"post-reboot-t{int(BASELINE_STABLE_DELAY_S)}s"
    baseline_stable = investigation["post_health_snapshots"].get(stable_label)
    baseline_pyronames: set[str] = set()
    if isinstance(baseline_stable, dict):
        baseline_pyronames = set(baseline_stable.get("pyronames", []))
        snapshots["baseline"] = ProcessSnapshot(
            label="baseline",
            raw="",
            serial_ok=True,
            ps_lines=list(baseline_stable.get("ps_lines", [])),
            ns_names=list(baseline_stable.get("ns_names", [])),
            protocol_ns=list(baseline_stable.get("protocol_ns", [])),
            orphan_ps_lines=list(baseline_stable.get("orphan_ps_lines", [])),
        )

    admin_token = await access_token_for_username(settings, ADMIN)
    async with FlexRobot(settings, access_token=admin_token) as admin:
        await ensure_run_state(
            admin,
            DesiredRunState.NO_CURRENT,
            ensure=True,
            capability_name="retest_rqa5791",
            signed_by=SIGNED_BY,
        )
        protocol_id = await resolve_protocol_id(admin)

        start = time.monotonic()
        created = await admin.runs.create_run(protocol_id=protocol_id)
        create_elapsed_s = time.monotonic() - start
        data = created.get("data") if isinstance(created, dict) else None
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError(f"create_run missing id: {created!r}")
        run_id = str(data["id"])

        snapshots["during_run"] = process_snapshot("during-run")

        status = (data.get("status") or "").lower()
        if status == "idle":
            with contextlib.suppress(RobotApiError):
                await admin.runs.stop(run_id)

        await release_current_run(admin, run_id, signed_by=SIGNED_BY)
        uncurrent_at = time.monotonic()

    checkpoint_results: dict[str, dict[str, object]] = {}
    ordered = sorted({max(0.0, d) for d in checkpoint_delays_s})
    elapsed_prev = 0.0
    for delay_s in ordered:
        wait_s = max(0.0, delay_s - elapsed_prev)
        if wait_s:
            await asyncio.sleep(wait_s)
        elapsed_prev = delay_s
        label = f"after-uncurrent-t{int(delay_s)}s"
        snap = process_snapshot(label)
        snapshots[label] = snap
        checkpoint_results[label] = {
            "delay_s": delay_s,
            "leaked_pyronames": sorted(
                pyronames_from_snapshot(snap) - baseline_pyronames
            ),
            "ps_count_delta": len(snap.ps_lines) - len(baseline_pyronames),
            **snapshot_to_dict(snap),
        }

    serial_failed = not all(s.serial_ok for s in snapshots.values())
    during = snapshots.get("during_run")

    leaked_by_checkpoint = {
        k: list(v.get("leaked_pyronames", []))
        for k, v in checkpoint_results.items()
    }
    ps_by_checkpoint = {
        k: int(v.get("remaining_ps_count", 0)) for k, v in checkpoint_results.items()
    }
    final_key = max(checkpoint_results, key=lambda k: checkpoint_results[k]["delay_s"])
    final = checkpoint_results[final_key]
    final_ps = int(final.get("remaining_ps_count", 0))
    post_settle_ps = [
        int(v.get("remaining_ps_count", 0))
        for v in checkpoint_results.values()
        if float(v.get("delay_s", 0)) >= SETTLE_WINDOW_S
    ]
    max_post_settle_ps = max(post_settle_ps) if post_settle_ps else final_ps
    settled_to_pool = (
        final_ps == PRELOADED_PS_EXPECTED and max_post_settle_ps <= PRELOADED_PS_EXPECTED
    )

    if serial_failed:
        passed: bool | None = None
        verdict = "INCONCLUSIVE (SSH/serial unavailable for ps/NS audit)"
    elif not baseline_pyronames:
        passed = None
        verdict = "INCONCLUSIVE (stable baseline pyronames missing)"
    elif settled_to_pool:
        passed = True
        verdict = (
            f"PASS: settled to {PRELOADED_PS_EXPECTED} pre-loaded workers after "
            f"{final['delay_s']:.0f}s (final_ps={final_ps}; runs pool may use a "
            f"new ot-protocol_* pyroname; timeline_ps={ps_by_checkpoint})"
        )
    else:
        passed = False
        verdict = (
            f"FAIL: ps count did not settle to {PRELOADED_PS_EXPECTED} pre-loaded "
            f"workers (final_ps={final_ps}, max_post_{SETTLE_WINDOW_S:.0f}s="
            f"{max_post_settle_ps}; timeline_ps={ps_by_checkpoint})"
        )

    result: dict[str, object] = {
        "ticket": "RQA-5791",
        "robot_host": settings.robot_host,
        "run_id": run_id,
        "create_elapsed_s": create_elapsed_s,
        "uncurrent_at_monotonic": uncurrent_at,
        "checkpoint_delays_s": list(ordered),
        "baseline_pyronames": sorted(baseline_pyronames),
        "baseline_ps_count": len(baseline_pyronames),
        "settled_to_pool": settled_to_pool,
        "settle_window_s": SETTLE_WINDOW_S,
        "ps_by_checkpoint": ps_by_checkpoint,
        "pyroname_changes_vs_baseline": leaked_by_checkpoint,
        "final_checkpoint": final_key,
        "baseline_investigation": investigation,
        "passed": passed,
        "verdict": verdict,
        "during_run_had_protocol_ns": (
            len(during.protocol_ns) > 0 if during and during.serial_ok else None
        ),
        "during_run_ps_count": (
            len(during.ps_lines) if during and during.serial_ok else None
        ),
        "checkpoints": checkpoint_results,
        "snapshots": {key: snapshot_to_dict(snap) for key, snap in snapshots.items()},
    }
    (ART / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Use extended settle timeline (0,30,60,120,180,300,600s after uncurrent).",
    )
    parser.add_argument(
        "--checkpoints",
        type=str,
        default=",".join(str(int(x)) for x in DEFAULT_CHECKPOINTS_S),
        help="Comma-separated seconds after uncurrent for ps/NS snapshots "
        "(default: 0,5,30,60,120).",
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        default=True,
        help="Reboot robot via SSH before audit (default: on).",
    )
    parser.add_argument(
        "--no-reboot",
        action="store_false",
        dest="reboot",
        help="Skip pre-test reboot.",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=1200.0,
        help="Seconds to wait for /health after reboot (default 1200).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    delays = tuple(
        float(part.strip())
        for part in (
            ",".join(str(int(x)) for x in EXTENDED_CHECKPOINTS_S)
            if args.extended
            else args.checkpoints
        ).split(",")
        if part.strip()
    )

    async def _run() -> dict[str, object]:
        if args.reboot:
            reboot_robot()
            await wait_for_robot(timeout_s=args.wait_timeout)
        return await run_audit(checkpoint_delays_s=delays)

    result = asyncio.run(_run())
    passed = result.get("passed")
    if passed is True:
        return 0
    if passed is False:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
