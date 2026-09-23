#!/usr/bin/env python3
"""Reproduce auditor onboarding: temp password login, rotation, re-login.

Manual CRS flow (App / ODD):
  1. Admin creates an Auditor account
  2. User receives a temporary password (admin reset)
  3. Auditor logs in with the temporary password
  4. App prompts for a new password; user sets it successfully
  5. Auditor cannot sign in with the new password (reported bug)

This script exercises the same path via auth-server HTTP APIs only.

Preconditions:
  - CRS on, ROBOT_USE_HTTPS=true, ALLOW_MUTATIONS=true
  - Bootstrap admin (default flex_harness_admin)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from flex_testing_agent.capabilities.user_management_suite import (
    run_account_type_onboarding_comparison,
    run_auditor_onboarding_retest,
)
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.fixtures.user_management import (
    EPHEMERAL_USERNAME_AUDITOR,
    EphemeralUserSpec,
)
from flex_testing_agent.orchestration.discover import settings_with_resolved_host

ART = Path("artifacts/retest-auditor-onboarding")


@dataclass
class ProbeReport:
    step: str
    http_status: int | None
    ok: bool | None
    account_type: str | None
    reset_password: bool | None
    detail: str


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reproduce auditor temp-password onboarding and re-login",
    )
    parser.add_argument(
        "--as-admin",
        default="flex_harness_admin",
        help="Bootstrap admin for ephemeral auditor setup (default: flex_harness_admin)",
    )
    parser.add_argument(
        "--username",
        default=EPHEMERAL_USERNAME_AUDITOR,
        help=f"Throwaway auditor username (default: {EPHEMERAL_USERNAME_AUDITOR})",
    )
    parser.add_argument(
        "--compare-user",
        action="store_true",
        help="Also run the same flow for accountType=user and compare GET self",
    )
    args = parser.parse_args()

    ART.mkdir(parents=True, exist_ok=True)
    settings = await settings_with_resolved_host(get_settings())
    print("Auditor onboarding temp-password retest")
    print(
        f"Robot host: {settings.robot_host} "
        f"https={settings.robot_use_https} "
        f"mutations={settings.allow_mutations}"
    )
    if not settings.allow_mutations:
        print("ERROR: set ALLOW_MUTATIONS=true before running this retest.")
        return 2

    if args.compare_user:
        comparison = await run_account_type_onboarding_comparison(
            settings,
            admin_username=args.as_admin,
        )
        for result in comparison.results:
            print(f"\n=== {result.account_type} ({result.username}) ===")
            for probe in result.probes:
                parts = [probe.step]
                if probe.http_status is not None:
                    parts.append(f"HTTP {probe.http_status}")
                if probe.ok is not None:
                    parts.append(f"ok={probe.ok}")
                if probe.account_type is not None:
                    parts.append(f"accountType={probe.account_type}")
                if probe.reset_password is not None:
                    parts.append(f"resetPassword={probe.reset_password}")
                if probe.detail:
                    parts.append(probe.detail)
                print("  " + " | ".join(parts))
            verdict = "PASS" if result.ok else "BUG_REPRODUCED"
            print(f"[{verdict}] post_rotation_get_self={result.post_rotation_get_self_status}")
            print(f"  {result.detail}")

        tag = "AUDITOR_SPECIFIC" if comparison.auditor_specific else "NOT_AUDITOR_SPECIFIC"
        print(f"\n[{tag}] {comparison.detail}")
        report = {
            "auditor_specific": comparison.auditor_specific,
            "detail": comparison.detail,
            "results": [
                {
                    "username": r.username,
                    "account_type": r.account_type,
                    "ok": r.ok,
                    "post_rotation_get_self_status": r.post_rotation_get_self_status,
                    "detail": r.detail,
                    "probes": [asdict(ProbeReport(
                        step=p.step,
                        http_status=p.http_status,
                        ok=p.ok,
                        account_type=p.account_type,
                        reset_password=p.reset_password,
                        detail=p.detail,
                    )) for p in r.probes],
                }
                for r in comparison.results
            ],
        }
        out = ART / "comparison-results.json"
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {out}")
        return 0 if comparison.auditor_specific else 1

    spec = EphemeralUserSpec.auditor_default()
    if args.username != EPHEMERAL_USERNAME_AUDITOR:
        spec = EphemeralUserSpec(
            username=args.username,
            password=spec.password,
            full_name=spec.full_name,
            account_type=spec.account_type,
        )

    result = await run_auditor_onboarding_retest(
        settings,
        admin_username=args.as_admin,
        spec=spec,
    )

    for probe in result.probes:
        parts = [probe.step]
        if probe.http_status is not None:
            parts.append(f"HTTP {probe.http_status}")
        if probe.ok is not None:
            parts.append(f"ok={probe.ok}")
        if probe.account_type is not None:
            parts.append(f"accountType={probe.account_type}")
        if probe.reset_password is not None:
            parts.append(f"resetPassword={probe.reset_password}")
        if probe.detail:
            parts.append(probe.detail)
        print("  " + " | ".join(parts))

    verdict = "PASS" if result.ok else "BUG_REPRODUCED"
    print(f"\n[{verdict}] {result.username} ({result.account_type})")
    print(f"  post_rotation_get_self={result.post_rotation_get_self_status}")
    print(f"  {result.detail}")

    report = {
        "username": result.username,
        "account_type": result.account_type,
        "ok": result.ok,
        "post_rotation_get_self_status": result.post_rotation_get_self_status,
        "verdict": verdict,
        "detail": result.detail,
        "probes": [
            asdict(
                ProbeReport(
                    step=p.step,
                    http_status=p.http_status,
                    ok=p.ok,
                    account_type=p.account_type,
                    reset_password=p.reset_password,
                    detail=p.detail,
                )
            )
            for p in result.probes
        ],
    }
    out = ART / "results.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
