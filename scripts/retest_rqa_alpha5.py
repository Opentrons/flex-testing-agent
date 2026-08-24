#!/usr/bin/env python3
"""Retest RQA-5791, RQA-5846, RQA-5854, RQA-5855 on KansasFLEX (alpha.5)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.reset_data import reset_robot_data
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.settings_reset import RUNS_HISTORY
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.fixtures.auth_settings_suite import default_smoke_protocol_path
from flex_testing_agent.models.auth_settings import AuthSettingsData
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


@dataclass
class StepResult:
    ticket: str
    name: str
    passed: bool | None
    detail: str


results: list[StepResult] = []


def record(ticket: str, name: str, passed: bool | None, detail: str) -> None:
    results.append(StepResult(ticket, name, passed, detail))
    status = "PASS" if passed else ("INCONCLUSIVE" if passed is None else "FAIL")
    print(f"[{status}] {ticket} {name}: {detail}")


async def introspect_scope(robot: FlexRobot, token: str, scope: str) -> bool:
    intro = await robot.oauth.introspect_token(token)
    if not intro.scope:
        return False
    return scope in intro.scope.split()


async def try_call(coro) -> tuple[int | None, str]:
    try:
        await coro()
        return 200, "ok"
    except RobotApiError as exc:
        return exc.status_code, (exc.body or "")[:300]


async def reset_runs_history(admin_robot: FlexRobot) -> None:
    await reset_robot_data(admin_robot, option_ids={RUNS_HISTORY})


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


async def create_and_uncurrent(
    robot: FlexRobot,
    protocol_id: str,
    *,
    signed_by: str,
) -> str:
    created = await robot.runs.create_run(protocol_id=protocol_id)
    data = created.get("data") if isinstance(created, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError(f"create_run missing id: {created!r}")
    run_id = str(data["id"])
    status = (data.get("status") or "").lower()
    if status == "idle":
        await robot.runs.stop(run_id)
    await release_current_run(robot, run_id, signed_by=signed_by)
    return run_id


def serial_ps_snapshot() -> str:
    cmd = (
        "ps -ef | grep run_process_entry_point | grep -v grep; "
        "echo '---'; "
        "python3 - <<'PY'\n"
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


async def test_rqa_5854(settings, admin_token: str) -> None:
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = AuthSettingsData.model_validate(
            (await admin.auth_settings.get_settings()).get("data", {})
        )
        run_ids: list[str] = []
        protocol_ids: list[str] = []
        try:
            await ensure_run_state(
                admin,
                DesiredRunState.NO_CURRENT,
                ensure=True,
                capability_name="retest_rqa_alpha5",
                signed_by="Flex Harness Retest",
            )

            await admin.auth_settings.patch_settings(
                {"requireAdminCredsForSignoffProtocol": False},
            )
            op_token = await access_token_for_username(settings, OPERATOR)
            await admin.auth_settings.patch_settings(
                {"requireAdminCredsForSignoffProtocol": True},
            )
            has_scope = await introspect_scope(admin, op_token, "run_signoff.write")
            protocol_id = await resolve_protocol_id(admin)
            protocol_ids.append(protocol_id)
            created = await admin.runs.create_run(protocol_id=protocol_id)
            run_id = str(created["data"]["id"])
            run_ids.append(run_id)
            if (created["data"].get("status") or "").lower() == "idle":
                await admin.runs.stop(run_id)
            async with FlexRobot(settings, access_token=op_token) as op_robot:
                sc, bd = await try_call(
                    lambda: op_robot.runs.sign_off(
                        run_id,
                        signed_by="Operator Stale Test",
                    ),
                )
            record(
                "RQA-5854",
                "stale token denied signoff when flag tightened",
                sc == 403,
                f"introspect run_signoff.write={has_scope}; signoff HTTP {sc}; body={bd[:120]!r}",
            )

            await admin.runs.sign_off(run_id, signed_by="Flex Harness Admin")
            await admin.runs.set_current(run_id, current=False)

            await admin.auth_settings.patch_settings(
                {"requireAdminCredsForSignoffProtocol": True},
            )
            op_token2 = await access_token_for_username(settings, OPERATOR)
            await admin.auth_settings.patch_settings(
                {"requireAdminCredsForSignoffProtocol": False},
            )
            has_scope2 = await introspect_scope(admin, op_token2, "run_signoff.write")
            protocol_id2 = await resolve_protocol_id(admin)
            protocol_ids.append(protocol_id2)
            created2 = await admin.runs.create_run(protocol_id=protocol_id2)
            run_id2 = str(created2["data"]["id"])
            run_ids.append(run_id2)
            if (created2["data"].get("status") or "").lower() == "idle":
                await admin.runs.stop(run_id2)
            async with FlexRobot(settings, access_token=op_token2) as op_robot:
                sc2, bd2 = await try_call(
                    lambda: op_robot.runs.sign_off(
                        run_id2,
                        signed_by="Operator Stale Test",
                    ),
                )
            record(
                "RQA-5854",
                "stale token allowed signoff when flag loosened",
                sc2 == 200,
                f"introspect run_signoff.write={has_scope2}; signoff HTTP {sc2}; body={bd2[:120]!r}",
            )
            await admin.runs.set_current(run_id2, current=False)
        finally:
            for rid in run_ids:
                with contextlib.suppress(Exception):
                    await release_current_run(
                        admin,
                        rid,
                        signed_by="Flex Harness Cleanup",
                    )
            for pid in protocol_ids:
                with contextlib.suppress(RobotApiError):
                    await admin.protocols.delete_protocol(pid)
            await admin.auth_settings.patch_settings(baseline.patch_fields())


async def test_rqa_5855(settings, admin_token: str) -> None:
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = AuthSettingsData.model_validate(
            (await admin.auth_settings.get_settings()).get("data", {})
        )
        try:
            await admin.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": False,
                    "requireAdminCredsWhenUpdatingRobotSoftware": False,
                },
            )
            op_token = await access_token_for_username(settings, OPERATOR)
            await admin.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": True,
                    "requireAdminCredsWhenUpdatingRobotSoftware": True,
                },
            )
            proto_scope = await introspect_scope(admin, op_token, "protocols.write")
            upd_scope = await introspect_scope(admin, op_token, "updates.write")
            async with FlexRobot(settings, access_token=op_token) as op_robot:
                sc_proto, bd_proto = await try_call(
                    lambda: op_robot.protocols.upload_protocol(SMOKE),
                )
                sc_upd, bd_upd = await try_call(lambda: op_robot.update.begin())
            if sc_upd == 200:
                with contextlib.suppress(RobotApiError):
                    await admin.update.cancel()
            record(
                "RQA-5855",
                "stale token denied protocol upload when flag tightened",
                sc_proto == 403,
                f"introspect protocols.write={proto_scope}; HTTP {sc_proto}; body={bd_proto[:120]!r}",
            )
            record(
                "RQA-5855",
                "stale token denied update begin when flag tightened",
                sc_upd == 403,
                f"introspect updates.write={upd_scope}; HTTP {sc_upd}; body={bd_upd[:120]!r}",
            )

            await admin.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": True,
                    "requireAdminCredsWhenUpdatingRobotSoftware": True,
                },
            )
            op_token2 = await access_token_for_username(settings, OPERATOR)
            await admin.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": False,
                    "requireAdminCredsWhenUpdatingRobotSoftware": False,
                },
            )
            proto_scope2 = await introspect_scope(admin, op_token2, "protocols.write")
            async with FlexRobot(settings, access_token=op_token2) as op_robot:
                try:
                    uploaded = await op_robot.protocols.upload_protocol(SMOKE)
                    sc_proto2 = 201
                    pid = (uploaded.get("data") or {}).get("id")
                    if pid:
                        with contextlib.suppress(RobotApiError):
                            await admin.protocols.delete_protocol(str(pid))
                except RobotApiError as exc:
                    sc_proto2 = exc.status_code or 0
            record(
                "RQA-5855",
                "stale token allowed protocol upload when flag loosened",
                sc_proto2 in {200, 201},
                f"introspect protocols.write={proto_scope2}; HTTP {sc_proto2}",
            )
        finally:
            await admin.auth_settings.patch_settings(baseline.patch_fields())


async def test_rqa_5846(settings, admin_token: str) -> None:
    async with FlexRobot(settings, access_token=admin_token) as admin:
        await ensure_run_state(
            admin,
            DesiredRunState.NO_CURRENT,
            ensure=True,
            capability_name="retest_rqa_alpha5",
            signed_by="Flex Harness Retest",
        )
        protocol_id = await resolve_protocol_id(admin)
        attempts = 10
        ok = 0
        fail_500 = 0
        other: list[str] = []
        for i in range(attempts):
            try:
                run_id = await create_and_uncurrent(
                    admin,
                    protocol_id,
                    signed_by="Flex Harness Retest",
                )
                ok += 1
                print(
                    f"  RQA-5846 cycle {i + 1}/{attempts}: 201 uncurrent ok "
                    f"run={run_id[:8]}…"
                )
            except RobotApiError as exc:
                if exc.status_code == 500:
                    fail_500 += 1
                    print(
                        f"  RQA-5846 cycle {i + 1}/{attempts}: 500 "
                        f"{(exc.body or '')[:100]!r}"
                    )
                else:
                    other.append(f"{exc.status_code}:{exc.path}")
                    print(
                        f"  RQA-5846 cycle {i + 1}/{attempts}: "
                        f"{exc.status_code} {exc.path}"
                    )
            await asyncio.sleep(0.5)
        record(
            "RQA-5846",
            f"{attempts}x create/uncurrent cycles",
            fail_500 == 0 and ok == attempts,
            f"201={ok} 500={fail_500} other={other or 'none'}",
        )


async def test_rqa_5791(settings, admin_token: str) -> None:
    async with FlexRobot(settings, access_token=admin_token) as admin:
        await ensure_run_state(
            admin,
            DesiredRunState.NO_CURRENT,
            ensure=True,
            capability_name="retest_rqa_alpha5",
            signed_by="Flex Harness Retest",
        )
        before = serial_ps_snapshot()
        protocol_id = await resolve_protocol_id(admin)
        run_id = await create_and_uncurrent(
            admin,
            protocol_id,
            signed_by="Flex Harness Retest",
        )
        await asyncio.sleep(2.0)
        after = serial_ps_snapshot()
        ART.mkdir(parents=True, exist_ok=True)
        (ART / "rqa5791-before.txt").write_text(before)
        (ART / "rqa5791-after.txt").write_text(after)
        orphan = "run_process_entry_point" in after
        record(
            "RQA-5791",
            "uncurrent leaves no orphan run_process_entry_point",
            not orphan,
            f"run_id={run_id[:8]}…; orphan processes in ps={orphan}",
        )


async def main() -> int:
    settings = await settings_with_resolved_host(get_settings())
    ART.mkdir(parents=True, exist_ok=True)

    async with FlexRobot(settings) as robot:
        h = await robot.session.get_json("/health")
        disk = (h.get("data") or {}).get("diskDetails") or {}
        print(
            "Robot",
            settings.robot_host,
            "version",
            (h.get("data") or {}).get("apiServerVersion"),
            "disk",
            disk,
        )

    admin_token = await access_token_for_username(settings, ADMIN)
    async with FlexRobot(settings, access_token=admin_token) as admin:
        try:
            await reset_runs_history(admin)
            print("reset runsHistory ok")
        except RobotApiError as exc:
            print(f"reset runsHistory skipped: HTTP {exc.status_code} {exc.path}")

    await test_rqa_5846(settings, admin_token)
    await test_rqa_5791(settings, admin_token)
    await test_rqa_5854(settings, admin_token)
    await test_rqa_5855(settings, admin_token)

    summary_path = ART / "summary.json"
    summary_path.write_text(
        json.dumps(
            [
                {
                    "ticket": r.ticket,
                    "name": r.name,
                    "passed": r.passed,
                    "detail": r.detail,
                }
                for r in results
            ],
            indent=2,
        )
    )
    print("\n=== Summary ===")
    for r in results:
        status = "PASS" if r.passed else ("INCONCLUSIVE" if r.passed is None else "FAIL")
        print(f"{status}\t{r.ticket}\t{r.name}")
    fails = sum(1 for r in results if r.passed is False)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
