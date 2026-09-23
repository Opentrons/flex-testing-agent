#!/usr/bin/env python3
"""Focused retest for RQA-6012: analysis must not require auth or documentation.

Maps to https://opentrons.atlassian.net/browse/RQA-6012

Uses Duolink Day 2 with **altered runtime parameters** on
``POST /protocols/{id}/analyses`` so robot-server runs a real reanalysis
(not the unchanged-protocol dedup path).

Preconditions:
  - CRS on, ROBOT_USE_HTTPS=true, ALLOW_MUTATIONS=true
  - Bootstrap admin (default flex_harness_admin)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from flex_testing_agent.capabilities.protocol_analysis_suite import run_rqa6012_retest
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.orchestration.discover import settings_with_resolved_host

ART = Path("artifacts/retest-rqa6012")
JIRA = "https://opentrons.atlassian.net/browse/RQA-6012"
DEFAULT_DUOLINK_PROTOCOL_ID = "1db50c61-04ad-4305-811f-3bca52e49fd4"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retest RQA-6012 analysis auth/documentation bypass",
    )
    parser.add_argument(
        "--as-admin",
        default="flex_harness_admin",
        help="Bootstrap admin for protocol upload cleanup (default: flex_harness_admin)",
    )
    parser.add_argument(
        "--protocol-path",
        default=None,
        help="Protocol file when uploading (default: duolink_multiwell_squarewell_day2.py)",
    )
    parser.add_argument(
        "--protocol-id",
        default=DEFAULT_DUOLINK_PROTOCOL_ID,
        help=(
            "Existing protocol id to reanalyze (default: KansasFLEX Duolink upload). "
            "Pass empty string to upload fresh instead."
        ),
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Do not delete the protocol after the retest.",
    )
    args = parser.parse_args()

    ART.mkdir(parents=True, exist_ok=True)
    settings = await settings_with_resolved_host(get_settings())
    print(f"RQA-6012 analysis bypass retest ({JIRA})")
    print(
        f"Robot host: {settings.robot_host} "
        f"https={settings.robot_use_https} "
        f"mutations={settings.allow_mutations}"
    )
    if not settings.allow_mutations:
        print("ERROR: set ALLOW_MUTATIONS=true before running this retest.")
        return 2

    protocol_id = args.protocol_id.strip() or None
    result = await run_rqa6012_retest(
        settings,
        admin_username=args.as_admin,
        protocol_path=args.protocol_path,
        protocol_id=protocol_id,
        skip_cleanup=args.skip_cleanup or protocol_id is not None,
    )

    print(f"Reanalysis RTPs: {json.dumps(result.reanalysis_rtps)}")
    for probe in result.probes:
        parts = [probe.step]
        if probe.http_status is not None:
            parts.append(f"HTTP {probe.http_status}")
        if probe.detail:
            parts.append(probe.detail)
        print("  " + " | ".join(parts))

    verdict = "PASS" if result.ok else "BUG_STILL_OPEN"
    print(f"\n[{verdict}] {result.detail}")
    if result.require_reason_for_interaction is not None:
        print(
            f"  requireReasonForInteraction={result.require_reason_for_interaction}"
        )

    report = {
        "ok": result.ok,
        "verdict": verdict,
        "detail": result.detail,
        "protocol_id": result.protocol_id,
        "reanalysis_rtps": result.reanalysis_rtps,
        "require_reason_for_interaction": result.require_reason_for_interaction,
        "probes": [p.model_dump(mode="json") for p in result.probes],
    }
    out = ART / "results.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
