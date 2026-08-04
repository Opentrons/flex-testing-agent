"""Unit tests for seed-runs helpers (no live robot)."""

from __future__ import annotations

import pytest

from flex_testing_agent.capabilities.seed_runs import SeedId, parse_seed_ids


@pytest.mark.unit
def test_parse_seed_ids_all_when_empty() -> None:
    assert parse_seed_ids(None) is None
    assert parse_seed_ids([]) is None


@pytest.mark.unit
def test_parse_seed_ids_accepts_hyphen_or_underscore() -> None:
    assert parse_seed_ids(["simple_home_move", "cancel-mid-run"]) == [
        SeedId.SIMPLE_HOME_MOVE,
        SeedId.CANCEL_MID_RUN,
    ]


@pytest.mark.unit
def test_parse_seed_ids_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown seed id"):
        parse_seed_ids(["not-a-seed"])
