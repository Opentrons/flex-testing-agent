"""Protocol paths and RTP helpers for analysis / reanalysis tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DUOLINK_PROTOCOL_NAME = "duolink_multiwell_squarewell_day2.py"


def default_duolink_protocol_path() -> Path:
    """Duolink Day 2 protocol copied from App protocol storage."""
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "docs/test-suggestions/protocols" / DUOLINK_PROTOCOL_NAME


def duolink_upload_runtime_parameter_values() -> dict[str, int | bool]:
    """RTP values used for initial upload analysis (protocol defaults)."""
    return {
        "num_sample": 96,
        "dry_run": False,
        "heat_on_deck": True,
        "use_lid": True,
        "use_temp": True,
    }


def duolink_reanalysis_runtime_parameter_values() -> dict[str, int | bool]:
    """Altered RTPs that differ from upload defaults and force a new analysis."""
    return {
        "num_sample": 48,
        "dry_run": True,
        "heat_on_deck": True,
        "use_lid": True,
        "use_temp": True,
    }


def analysis_request_data(
    *,
    run_time_parameter_values: dict[str, Any] | None = None,
    force_re_analyze: bool | None = None,
) -> dict[str, Any]:
    """Build ``POST /protocols/{id}/analyses`` JSON ``data`` object."""
    data: dict[str, Any] = {}
    if run_time_parameter_values:
        data["runTimeParameterValues"] = run_time_parameter_values
    if force_re_analyze is not None:
        data["forceReAnalyze"] = force_re_analyze
    return data
