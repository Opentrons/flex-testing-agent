#!/usr/bin/env python3
"""Focused retest for RQA-5952: admin actions must revoke cached target tokens.

Maps to the Gherkin matrix in https://opentrons.atlassian.net/browse/RQA-5952

Each scenario:
  1. Create throwaway target user (flex_um_tok_rev)
  2. Mint an access token once and cache it (no remint after admin action)
  3. Prove cached token works: GET /auth/users/self → 200
  4. Administrator performs the action on the target user
  5. Reuse the same cached token:
     - revoke cases: GET + PATCH /auth/users/self → 401/403 (404 after delete)
     - legal-name case: GET + PATCH /auth/users/self → 200
  6. Record OAuth introspection ``active`` for revoked cases

Preconditions (robot must be prepared separately):
  - CRS / accessControlEnabled=true
  - ROBOT_USE_HTTPS=true with CA trust
  - ALLOW_MUTATIONS=true
  - Bootstrap admin (default flex_harness_admin)
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from flex_testing_agent.capabilities.user_management_suite import (
    Rqa5952ScenarioResult,
    run_rqa5952_token_matrix,
)
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.orchestration.discover import settings_with_resolved_host

ART = Path("artifacts/retest-rqa5952")
JIRA = "https://opentrons.atlassian.net/browse/RQA-5952"


@dataclass
class ScenarioReport:
    scenario_id: str
    action: str
    expect_revoked: bool
    ok: bool
    detail: str
    verdict: str


def _verdict(item: Rqa5952ScenarioResult) -> str:
    if item.ok:
        return "PASS"
    if item.expect_revoked:
        return "BUG_STILL_OPEN"
    return "UNEXPECTED_FAIL"


def _to_report(item: Rqa5952ScenarioResult) -> ScenarioReport:
    return ScenarioReport(
        scenario_id=item.scenario_id,
        action=item.action,
        expect_revoked=item.expect_revoked,
        ok=item.ok,
        detail=item.detail,
        verdict=_verdict(item),
    )


async def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    settings = await settings_with_resolved_host(get_settings())
    print(f"RQA-5952 cached-token matrix retest ({JIRA})")
    print(
        f"Robot host: {settings.robot_host} "
        f"https={settings.robot_use_https} "
        f"mutations={settings.allow_mutations}"
    )
    if not settings.allow_mutations:
        print("ERROR: set ALLOW_MUTATIONS=true before running this retest.")
        return 2
    if not settings.robot_use_https:
        print("WARNING: ROBOT_USE_HTTPS=true is expected for CRS-on retests.")

    results = await run_rqa5952_token_matrix(settings)
    reports = [_to_report(item) for item in results]

    for report in reports:
        print(
            f"[{report.verdict}] {report.scenario_id}: admin {report.action} "
            f"(expect_revoked={report.expect_revoked})"
        )
        print(f"  {report.detail[:240]}")

    payload = [asdict(report) for report in reports]
    out = ART / "results.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")

    failed = [report for report in reports if not report.ok]
    if not failed:
        print("All RQA-5952 scenarios passed.")
        return 0

    still_open = [report for report in failed if report.expect_revoked]
    if still_open and len(still_open) == len(failed):
        print(
            f"{len(still_open)} revocation scenario(s) still fail "
            "(cached token not rejected)."
        )
        return 1

    print(f"{len(failed)} scenario(s) failed unexpectedly.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
