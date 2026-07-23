"""Tests for test-suggestion site generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from flex_testing_agent.site.publish import (
    linkify,
    load_suggestions,
    publish_test_suggestion_pages,
)


@pytest.mark.unit
def test_load_repo_suggestions() -> None:
    suggestions = load_suggestions(Path("docs/test-suggestions"))
    ids = {item.id for item in suggestions}
    assert "9.1.2-module-usb-reconnect" in ids
    assert "9.1.2-96ch-row-centering" in ids
    assert "9.1.2-odd-loop-rtp-setup" in ids
    validated = next(s for s in suggestions if s.id == "9.1.2-module-usb-reconnect")
    assert validated.status == "validated"
    assert validated.tests[0].id == "B1"
    odd = next(s for s in suggestions if s.id == "9.1.2-odd-loop-rtp-setup")
    assert odd.status == "suggested"
    assert odd.release.robot_os == "9.1.2-alpha.1"
    assert {t.id for t in odd.tests} >= {"E1", "E2", "E3"}
    assert odd.release.tickets[0].key == "AUTH-3041"


@pytest.mark.unit
def test_linkify_jira_and_prs() -> None:
    html = linkify(
        "See AUTH-3041 and #21946 for context.",
        pr_urls={21946: "https://github.com/Opentrons/opentrons/pull/21946"},
    )
    assert 'href="https://opentrons.atlassian.net/browse/AUTH-3041"' in html
    assert ">AUTH-3041<" in html
    assert 'href="https://github.com/Opentrons/opentrons/pull/21946"' in html
    assert ">#21946<" in html


@pytest.mark.unit
def test_publish_writes_index_and_pages(tmp_path: Path) -> None:
    written = publish_test_suggestion_pages(
        suggestions_dir=Path("docs/test-suggestions"),
        output_dir=tmp_path,
    )
    paths = {path.name for path in written}
    assert "index.html" in paths
    assert ".nojekyll" in paths
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Temperature module USB reconnect" in index
    assert "9.1.2-module-usb-reconnect.html" in index
    assert "opentrons.atlassian.net/browse/AUTH-3041" in index
    detail = (tmp_path / "suggestions" / "9.1.2-odd-loop-rtp-setup.html").read_text(
        encoding="utf-8"
    )
    assert "wait-absent" not in detail
    assert "chip jira" in detail
    assert "chip pr" in detail
    assert "https://opentrons.atlassian.net/browse/AUTH-3041" in detail
    assert "https://github.com/Opentrons/opentrons/pull/21946" in detail
    assert "https://github.com/Opentrons/opentrons/pull/21905" in detail
    assert "Repro path from" in detail
    assert "#21905" in detail
