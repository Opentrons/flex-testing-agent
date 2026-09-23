#!/usr/bin/env python3
"""Inspect on-robot robot_server.db snapshots for RQA-5797 legacy StateSummary rows.

Run on KansasFLEX (serial/SSH), not on the laptop::

  python3 /tmp/inspect_robot_db_snapshots.py

Copy to the robot first if needed.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

PATHS = (
    "/var/lib/opentrons-robot-server/robot_server.db",
    "/var/lib/opentrons-robot-server/16/robot_server.db",
    "/var/lib/opentrons-robot-server/19/robot_server.db",
)
JIRA_IDS = {
    "c5a741fa-2c7b-4426-8d05-a3b010b93606",
    "c4c5a33c-e254-48ef-9961-404b00c1bd79",
}
NEEDLE = "errorRecoveryCameraEnabled"


def inspect_db(path: str) -> dict[str, Any]:
    out: dict[str, Any] = {"path": path}
    if not os.path.exists(path):
        out["missing"] = True
        return out
    out["size_bytes"] = os.path.getsize(path)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
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
    cols = [
        row[1] for row in cur.execute(f"PRAGMA table_info({run_table})").fetchall()
    ]
    out["run_columns"] = cols
    id_col = "id" if "id" in cols else "run_id"
    has_ss = "state_summary" in cols
    select = f"SELECT {id_col}, state_summary FROM {run_table}" if has_ss else f"SELECT {id_col} FROM {run_table}"
    rows = cur.execute(select).fetchall()
    out["run_count"] = len(rows)
    jira_present: list[str] = []
    legacy_candidates: list[dict[str, str]] = []
    for row in rows:
        rid = str(row[0])
        ss = row[1] if has_ss and len(row) > 1 else None
        if rid in JIRA_IDS:
            jira_present.append(rid)
        if not ss:
            continue
        has_camera = "cameraSettings" in ss
        has_needle = NEEDLE in ss
        if has_camera and not has_needle:
            legacy_candidates.append(
                {
                    "id": rid,
                    "reason": "cameraSettings without errorRecoveryCameraEnabled",
                    "preview": ss[:240],
                }
            )
    out["jira_ids_present"] = jira_present
    out["legacy_candidates"] = legacy_candidates[:20]
    out["legacy_candidate_count"] = len(legacy_candidates)
    con.close()
    return out


def main() -> None:
    results = [inspect_db(path) for path in PATHS]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
