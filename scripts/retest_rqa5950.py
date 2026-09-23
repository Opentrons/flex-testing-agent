#!/usr/bin/env python3
"""Focused retest for RQA-5950: self username change with cached session token.

Maps to https://opentrons.atlassian.net/browse/RQA-5950

Flow (cached token, no remint until cleanup):
  1. Create/login throwaway user (default flex_harness_um_crud)
  2. Mint access token once and cache it
  3. GET /auth/users/self + introspect (baseline)
  4. PATCH /auth/users/self username → temp name (same token)
  5. Reuse cached token: introspect, GET self, PATCH fullName
  6. Expect 200 on post-rename GET + PATCH (bug was HTTP 500)
  7. Remint, restore original username, cleanup temp user

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

from flex_testing_agent.capabilities.user_management_suite import run_rqa5950_retest
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.fixtures.user_management import EPHEMERAL_USERNAME_SELF_TMP
from flex_testing_agent.orchestration.discover import settings_with_resolved_host

ART = Path("artifacts/retest-rqa5950")
JIRA = "https://opentrons.atlassian.net/browse/RQA-5950"


@dataclass
class ProbeReport:
    step: str
    http_status: int | None
    introspect_active: bool | None
    introspect_username: str | None
    detail: str


async def main() -> int:
    parser = argparse.ArgumentParser(description="Retest RQA-5950 cached-token self rename")
    parser.add_argument(
        "--as-admin",
        default="flex_harness_admin",
        help="Bootstrap admin for ephemeral user setup (default: flex_harness_admin)",
    )
    parser.add_argument(
        "--subject-username",
        default=None,
        help="Subject user to rename (default: ephemeral flex_harness_um_crud)",
    )
    parser.add_argument(
        "--temp-username",
        default=EPHEMERAL_USERNAME_SELF_TMP,
        help=f"Temporary username during rename (default: {EPHEMERAL_USERNAME_SELF_TMP})",
    )
    args = parser.parse_args()

    ART.mkdir(parents=True, exist_ok=True)
    settings = await settings_with_resolved_host(get_settings())
    print(f"RQA-5950 self-username cached-token retest ({JIRA})")
    print(
        f"Robot host: {settings.robot_host} "
        f"https={settings.robot_use_https} "
        f"mutations={settings.allow_mutations}"
    )
    if not settings.allow_mutations:
        print("ERROR: set ALLOW_MUTATIONS=true before running this retest.")
        return 2

    result = await run_rqa5950_retest(
        settings,
        admin_username=args.as_admin,
        subject_username=args.subject_username,
        temp_username=args.temp_username,
    )

    for probe in result.probes:
        parts = [probe.step]
        if probe.http_status is not None:
            parts.append(f"HTTP {probe.http_status}")
        if probe.introspect_active is not None:
            parts.append(f"active={probe.introspect_active}")
        if probe.introspect_username:
            parts.append(f"username={probe.introspect_username}")
        if probe.detail:
            parts.append(probe.detail)
        print("  " + " | ".join(parts))

    verdict = "PASS" if result.ok else "BUG_STILL_OPEN"
    print(f"\n[{verdict}] {result.subject_username} → {result.temp_username}")
    print(f"  {result.detail}")

    report = {
        "subject_username": result.subject_username,
        "temp_username": result.temp_username,
        "ok": result.ok,
        "verdict": verdict,
        "detail": result.detail,
        "probes": [asdict(ProbeReport(
            step=p.step,
            http_status=p.http_status,
            introspect_active=p.introspect_active,
            introspect_username=p.introspect_username,
            detail=p.detail,
        )) for p in result.probes],
    }
    out = ART / "results.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
