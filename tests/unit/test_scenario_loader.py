"""Unit tests for scenario metadata loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from flex_testing_agent.scenarios.loader import load_scenario_metadata


@pytest.mark.unit
def test_load_inspect_scenario_yaml() -> None:
    path = Path(__file__).resolve().parents[2] / "scenarios" / "inspect-robot.yaml"
    meta = load_scenario_metadata(path)
    assert meta.name == "inspect-robot"
    assert meta.risk_level == "READ_ONLY"
    assert meta.restore_baseline is False
