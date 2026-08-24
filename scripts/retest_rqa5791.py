#!/usr/bin/env python3
"""Post-reboot RQA-5791 audit: uncurrent should tear down protocol subprocesses.

Repro aligned with Jira RQA-5791:
1. Baseline ps + Pyro5 NS (after reboot, before create)
2. POST /runs -> confirm ot-protocol_* in NS + run_process_entry_point in ps
3. Stop idle run if needed, uncurrent
4. ps + NS immediately and ~5s after uncurrent
5. FAIL if run_process_entry_point remains without matching NS registration
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
from dataclasses import dataclass, field
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
from flex_testing_agent.serial_console import resolve_serial_port

ADMIN = "flex_test_admin"
SIGNED_BY = "Flex Harness RQA-5791 Retest"
SMOKE = default_smoke_protocol_path()
ROOT = Path(__file__).resolve().parents[1]
ART = Path("artifacts/retest-rqa5791")

SERIAL_SNAPSHOT_CMD = (
    "ps -ef | grep run_process_entry_point | grep -v grep || true; "
    "echo '---NS---'; "
    "python3 -c \"import Pyro5.api as pyro; "
    "ns=pyro.locate_ns(); "
    "print('\\\\n'.join(sorted(ns.list()))\""
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
            if section == "ps" and "run_process_entry_point" in line:
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
            return "serial unavailable"
        return (
            f"ps={len(self.ps_lines)} protocol_ns={len(self.protocol_ns)} "
            f"orphan_ps={len(self.orphan_ps_lines)}"
        )


def _breakin_serial_shell(ser: object) -> None:
    import serial  # noqa: F401 — type context for callers

    assert hasattr(ser, "write")
    ser.write(b"\x03\x03\x03\n")  # type: ignore[union-attr]
    time.sleep(0.4)
    ser.write(b"\n")  # type: ignore[union-attr]
    time.sleep(0.3)


def reboot_robot() -> None:
    print("Rebooting KansasFLEX via FTDI serial…")
    serial_run("reboot", label="reboot")


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
        await asyncio.sleep(5.0)
    raise TimeoutError(f"Timed out waiting for robot health ({last_error})")


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


def serial_snapshot(label: str) -> ProcessSnapshot:
    raw = serial_run(SERIAL_SNAPSHOT_CMD.strip(), label=label)
    if "Could not obtain" in raw and label not in raw:
        # Wrap body-only output for parser consistency.
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


async def run_audit(*, post_uncurrent_delay_s: float) -> dict[str, object]:
    settings = await settings_with_resolved_host(get_settings())
    ART.mkdir(parents=True, exist_ok=True)

    snapshots: dict[str, ProcessSnapshot] = {}
    run_id: str | None = None
    create_elapsed_s: float | None = None

    snapshots["baseline"] = serial_snapshot("baseline")

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

        snapshots["during_run"] = serial_snapshot("during-run")

        status = (data.get("status") or "").lower()
        if status == "idle":
            with contextlib.suppress(RobotApiError):
                await admin.runs.stop(run_id)

        await release_current_run(admin, run_id, signed_by=SIGNED_BY)

    snapshots["after_uncurrent_immediate"] = serial_snapshot("after-uncurrent-immediate")
    await asyncio.sleep(post_uncurrent_delay_s)
    snapshots["after_uncurrent_delayed"] = serial_snapshot("after-uncurrent-delayed")

    serial_failed = not all(s.serial_ok for s in snapshots.values())
    during = snapshots["during_run"]
    immediate = snapshots["after_uncurrent_immediate"]
    delayed = snapshots["after_uncurrent_delayed"]

    # RQA-5791: after uncurrent, NS ot-protocol gone but ps processes remain.
    orphan_immediate = immediate.orphan_ps_lines or (
        immediate.ps_lines
        if immediate.ps_lines and not immediate.protocol_ns
        else []
    )
    orphan_delayed = delayed.orphan_ps_lines or (
        delayed.ps_lines if delayed.ps_lines and not delayed.protocol_ns else []
    )

    if serial_failed:
        passed: bool | None = None
        verdict = "INCONCLUSIVE (serial shell unavailable for ps/NS audit)"
    elif orphan_immediate or orphan_delayed:
        passed = False
        verdict = (
            f"FAIL: orphan run_process_entry_point after uncurrent "
            f"(immediate orphan_ps={len(orphan_immediate)} "
            f"delayed orphan_ps={len(orphan_delayed)})"
        )
    else:
        passed = True
        verdict = "PASS: no orphan protocol subprocess after uncurrent"

    result: dict[str, object] = {
        "ticket": "RQA-5791",
        "robot_host": settings.robot_host,
        "run_id": run_id,
        "create_elapsed_s": create_elapsed_s,
        "post_uncurrent_delay_s": post_uncurrent_delay_s,
        "passed": passed,
        "verdict": verdict,
        "during_run_had_protocol_ns": len(during.protocol_ns) > 0 if during.serial_ok else None,
        "during_run_ps_count": len(during.ps_lines) if during.serial_ok else None,
        "snapshots": {
            key: {
                "summary": snap.summary(),
                "serial_ok": snap.serial_ok,
                "ps_lines": snap.ps_lines,
                "protocol_ns": snap.protocol_ns,
                "orphan_ps_lines": snap.orphan_ps_lines,
            }
            for key, snap in snapshots.items()
        },
    }
    (ART / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--post-uncurrent-delay",
        type=float,
        default=5.0,
        help="Seconds to wait before delayed ps/NS snapshot (default 5).",
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        default=True,
        help="Reboot robot via serial before audit (default: on).",
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

    async def _run() -> dict[str, object]:
        if args.reboot:
            reboot_robot()
            await wait_for_robot(timeout_s=args.wait_timeout)
        return await run_audit(post_uncurrent_delay_s=args.post_uncurrent_delay)

    result = asyncio.run(_run())
    passed = result.get("passed")
    if passed is True:
        return 0
    if passed is False:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
