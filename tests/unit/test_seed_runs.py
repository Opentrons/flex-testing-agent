"""Unit tests for seed-runs helpers (no live robot)."""

from __future__ import annotations

from typing import cast

import pytest

from flex_testing_agent.capabilities.seed_runs import (
    SEED_SIGNOFF_LABEL,
    SeedId,
    parse_seed_ids,
    seed_signoff_label,
)
from flex_testing_agent.robots.flex import FlexRobot


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
def test_parse_seed_ids_new_pause_and_failed() -> None:
    assert parse_seed_ids(["pause_mid_run", "failed-intentional"]) == [
        SeedId.PAUSE_MID_RUN,
        SeedId.FAILED_INTENTIONAL,
    ]


@pytest.mark.unit
def test_parse_seed_ids_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown seed id"):
        parse_seed_ids(["not-a-seed"])


class _FakeSession:
    def __init__(self, token: str | None) -> None:
        self.access_token = token


class _FakeSettings:
    def __init__(self, notes: str | None) -> None:
        self.robot_user_notes = notes


class _FakeRobot:
    def __init__(self, token: str | None, notes: str | None) -> None:
        self.session = _FakeSession(token)
        self.settings = _FakeSettings(notes)


@pytest.mark.unit
def test_seed_signoff_label_none_without_oauth() -> None:
    assert seed_signoff_label(cast(FlexRobot, _FakeRobot(None, None))) is None


@pytest.mark.unit
def test_seed_signoff_label_default_with_oauth() -> None:
    assert (
        seed_signoff_label(cast(FlexRobot, _FakeRobot("token", None)))
        == SEED_SIGNOFF_LABEL
    )


@pytest.mark.unit
def test_seed_signoff_label_uses_configured_notes() -> None:
    assert (
        seed_signoff_label(cast(FlexRobot, _FakeRobot("token", "qa seed"))) == "qa seed"
    )
