"""Tests for test-suggestion site generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from flex_testing_agent.site.publish import (
    load_suggestions,
    publish_test_suggestion_pages,
)


@pytest.mark.unit
def test_load_repo_suggestions() -> None:
    suggestions = load_suggestions(Path("docs/test-suggestions"))
    ids = {item.id for item in suggestions}
    assert "9.1.2-module-usb-reconnect" in ids
    assert "9.1.2-96ch-row-centering" in ids
    validated = next(s for s in suggestions if s.id == "9.1.2-module-usb-reconnect")
    assert validated.status == "validated"
    assert validated.tests[0].id == "B1"


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
    detail = (tmp_path / "suggestions" / "9.1.2-module-usb-reconnect.html").read_text(
        encoding="utf-8"
    )
    assert "wait-absent" in detail
    assert "validated" in detail
