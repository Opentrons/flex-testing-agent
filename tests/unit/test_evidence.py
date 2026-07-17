"""Evidence store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from flex_testing_agent.evidence.store import EvidenceStore


@pytest.mark.unit
def test_evidence_write_json(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "run")
    path = store.write_json("health", {"name": "Kansas", "password": "nope"})
    text = path.read_text(encoding="utf-8")
    assert "Kansas" in text
    assert "nope" not in text
    assert "***REDACTED***" in text
