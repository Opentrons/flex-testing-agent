#!/usr/bin/env python3
"""Round 2 retest after disk cleanup (refreshes tokens between sections)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
from pathlib import Path

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.fixtures.auth_settings_suite import default_smoke_protocol_path
from flex_testing_agent.models.auth_settings import AuthSettingsData
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
)
from flex_testing_agent.robots.flex import FlexRobot

ADMIN = "flex_test_admin"
OPERATOR = "flex_test_operator"
ART = Path("artifacts/retest-rqa-alpha5")
SMOKE = default_smoke_protocol_path()
ROOT = Path(__file__).resolve().parents[1]
results: list[dict[str, object]] = []


def log(ticket: str, name: str, passed: bool | None, detail: str) -> None:
    results.append({"ticket": ticket, "name": name, "passed": passed, "detail": detail})
    tag = "PASS" if passed else ("SKIP" if passed is None else "FAIL")
    print(f"[{tag}] {ticket} {name}: {detail}")


async def admin_robot(settings):
    tok = await access_token_for_username(settings, ADMIN)
    return FlexRobot(settings, access_token=tok), tok


async def has_scope(robot: FlexRobot, token: str, scope: str) -> bool:
    intro = await robot.oauth.introspect_token(token)
    return scope in (intro.scope or "").split()


async def resolve_protocol_id(robot: FlexRobot) -> str:
    for summary in await robot.protocols.list_protocol_summaries():
        files = summary.get("files")
        if isinstance(files, list) and any(
            isinstance(f, dict) and f.get("name") == SMOKE.name and f.get("role") == "main"
            for f in files
        ):
            if summary.get("id"):
                return str(summary["id"])
    uploaded = await robot.protocols.upload_protocol(SMOKE)
    return str(uploaded["data"]["id"])


async def create_and_uncurrent(robot: FlexRobot, protocol_id: str) -> str:
    created = await robot.runs.create_run(protocol_id=protocol_id)
    run_id = str(created["data"]["id"])
    if (created["data"].get("status") or "").lower() == "idle":
        await robot.runs.stop(run_id)
    await release_current_run(robot, run_id, signed_by="Flex Harness Retest")
    return run_id


def serial_snapshot() -> str:
    cmd = (
        "ps -ef | grep run_process_entry_point | grep -v grep; "
        "echo '---'; python3 - <<'PY'\n"
        "import Pyro4\n"
        "ns = Pyro4.locateNS(host='127.0.0.1', port=9090)\n"
        "print('NS', sorted(ns.list()))\n"
        "PY"
    )
    proc = subprocess.run(
        ["uv", "run", "flex-test", "serial", "run", cmd],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


async def test_5846(settings) -> None:
    ok = fail500 = 0
    errors: list[str] = []
    protocol_id: str | None = None
    for i in range(10):
        robot, _ = await admin_robot(settings)
        async with robot:
            if i == 0:
                await ensure_run_state(
                    robot,
                    DesiredRunState.NO_CURRENT,
                    ensure=True,
                    capability_name="retest",
                    signed_by="Flex Harness Retest",
                )
                protocol_id = await resolve_protocol_id(robot)
            assert protocol_id is not None
            try:
                rid = await create_and_uncurrent(robot, protocol_id)
                ok += 1
                print(f"  cycle {i+1}: 201 {rid[:8]}")
            except RobotApiError as exc:
                body = (exc.body or "")[:200]
                if exc.status_code == 500:
                    fail500 += 1
                    errors.append(body)
                    print(f"  cycle {i+1}: 500 {body[:80]}")
                else:
                    errors.append(f"{exc.status_code}:{exc.path}:{body[:60]}")
                    print(f"  cycle {i+1}: {exc.status_code} {exc.path}")
        await asyncio.sleep(0.5)
    log(
        "RQA-5846",
        "10x create/uncurrent",
        fail500 == 0 and ok == 10,
        f"201={ok} 500={fail500} samples={errors[:3]}",
    )


async def test_5791(settings) -> None:
    robot, _ = await admin_robot(settings)
    async with robot:
        await ensure_run_state(
            robot,
            DesiredRunState.NO_CURRENT,
            ensure=True,
            capability_name="retest",
            signed_by="Flex Harness Retest",
        )
        before = serial_snapshot()
        protocol_id = await resolve_protocol_id(robot)
        run_id = await create_and_uncurrent(robot, protocol_id)
        await asyncio.sleep(3)
        after = serial_snapshot()
        ART.mkdir(parents=True, exist_ok=True)
        (ART / "rqa5791-after-round2.txt").write_text(after)
        orphan = "run_process_entry_point" in after
        ot_in_ns = any("ot-protocol" in line for line in after.splitlines())
        log(
            "RQA-5791",
            "uncurrent orphan processes",
            not orphan,
            f"run={run_id[:8]} orphan_ps={orphan} ot_protocol_in_ns={ot_in_ns}",
        )


async def test_5854(settings) -> None:
    robot, _ = await admin_robot(settings)
    async with robot:
        baseline = await robot.auth_settings.get_settings()
        run_id: str | None = None
        pid: str | None = None
        try:
            await ensure_run_state(
                robot,
                DesiredRunState.NO_CURRENT,
                ensure=True,
                capability_name="retest",
                signed_by="Flex Harness Retest",
            )
            # tighten
            await robot.auth_settings.patch_settings({"requireAdminCredsForSignoffProtocol": False})
            op_tok = await access_token_for_username(settings, OPERATOR)
            await robot.auth_settings.patch_settings({"requireAdminCredsForSignoffProtocol": True})
            intro_tight = await has_scope(robot, op_tok, "run_signoff.write")
            pid = await resolve_protocol_id(robot)
            created = await robot.runs.create_run(protocol_id=pid)
            run_id = str(created["data"]["id"])
            if (created["data"].get("status") or "").lower() == "idle":
                await robot.runs.stop(run_id)
            async with FlexRobot(settings, access_token=op_tok) as op:
                try:
                    await op.runs.sign_off(run_id, signed_by="Operator")
                    sc_tight = 200
                except RobotApiError as exc:
                    sc_tight = exc.status_code or 0
            log(
                "RQA-5854",
                "tighten stale token signoff denied",
                sc_tight == 403 and not intro_tight,
                f"introspect={intro_tight} HTTP={sc_tight}",
            )
            await robot.runs.sign_off(run_id, signed_by="Admin")
            await robot.runs.set_current(run_id, current=False)
            run_id = None

            # loosen
            await robot.auth_settings.patch_settings({"requireAdminCredsForSignoffProtocol": True})
            op_tok2 = await access_token_for_username(settings, OPERATOR)
            await robot.auth_settings.patch_settings({"requireAdminCredsForSignoffProtocol": False})
            intro_loose = await has_scope(robot, op_tok2, "run_signoff.write")
            pid2 = await resolve_protocol_id(robot)
            created2 = await robot.runs.create_run(protocol_id=pid2)
            run_id2 = str(created2["data"]["id"])
            if (created2["data"].get("status") or "").lower() == "idle":
                await robot.runs.stop(run_id2)
            async with FlexRobot(settings, access_token=op_tok2) as op:
                try:
                    await op.runs.sign_off(run_id2, signed_by="Operator")
                    sc_loose = 200
                except RobotApiError as exc:
                    sc_loose = exc.status_code or 0
            log(
                "RQA-5854",
                "loosen stale token signoff allowed",
                sc_loose == 200 and intro_loose,
                f"introspect={intro_loose} HTTP={sc_loose}",
            )
            await robot.runs.set_current(run_id2, current=False)
        finally:
            if run_id:
                with contextlib.suppress(Exception):
                    await release_current_run(robot, run_id, signed_by="Cleanup")
            await robot.auth_settings.patch_settings(baseline.patch_fields())


async def test_5855(settings) -> None:
    robot, _ = await admin_robot(settings)
    async with robot:
        baseline = await robot.auth_settings.get_settings()
        try:
            await robot.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": False,
                    "requireAdminCredsWhenUpdatingRobotSoftware": False,
                }
            )
            op_tok = await access_token_for_username(settings, OPERATOR)
            await robot.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": True,
                    "requireAdminCredsWhenUpdatingRobotSoftware": True,
                }
            )
            p_scope = await has_scope(robot, op_tok, "protocols.write")
            u_scope = await has_scope(robot, op_tok, "updates.write")
            async with FlexRobot(settings, access_token=op_tok) as op:
                try:
                    await op.protocols.upload_protocol(SMOKE)
                    sc_p = 201
                except RobotApiError as exc:
                    sc_p = exc.status_code or 0
                try:
                    await op.update.begin()
                    sc_u = 200
                except RobotApiError as exc:
                    sc_u = exc.status_code or 0
            if sc_u == 200:
                with contextlib.suppress(RobotApiError):
                    await robot.update.cancel()
            log(
                "RQA-5855",
                "tighten stale token denied",
                sc_p == 403 and sc_u == 403 and not p_scope and not u_scope,
                f"intro p={p_scope} u={u_scope} HTTP p={sc_p} u={sc_u}",
            )

            await robot.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": True,
                    "requireAdminCredsWhenUpdatingRobotSoftware": True,
                }
            )
            op_tok2 = await access_token_for_username(settings, OPERATOR)
            await robot.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": False,
                    "requireAdminCredsWhenUpdatingRobotSoftware": False,
                }
            )
            p_scope2 = await has_scope(robot, op_tok2, "protocols.write")
            async with FlexRobot(settings, access_token=op_tok2) as op:
                try:
                    up = await op.protocols.upload_protocol(SMOKE)
                    sc_p2 = 201
                    dup = (up.get("data") or {}).get("id")
                    if dup:
                        with contextlib.suppress(RobotApiError):
                            await robot.protocols.delete_protocol(str(dup))
                except RobotApiError as exc:
                    sc_p2 = exc.status_code or 0
            log(
                "RQA-5855",
                "loosen stale token allowed upload",
                sc_p2 in {200, 201} and p_scope2,
                f"introspect={p_scope2} HTTP={sc_p2}",
            )
        finally:
            await robot.auth_settings.patch_settings(baseline.patch_fields())


async def main() -> int:
    settings = await settings_with_resolved_host(get_settings())
    ART.mkdir(parents=True, exist_ok=True)
    async with FlexRobot(settings) as r:
        dd = (await r.session.get_json("/health")).get("disk_details") or {}
        print("disk", dd)
    await test_5846(settings)
    await test_5791(settings)
    await test_5854(settings)
    await test_5855(settings)
    (ART / "summary-round2.json").write_text(json.dumps(results, indent=2))
    print("\n=== Summary ===")
    for row in results:
        p = row["passed"]
        tag = "PASS" if p else ("SKIP" if p is None else "FAIL")
        print(f"{tag}\t{row['ticket']}\t{row['name']}")
    return 0 if all(r["passed"] for r in results if r["passed"] is not None) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
