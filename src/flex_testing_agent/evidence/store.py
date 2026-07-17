"""Filesystem evidence store under ARTIFACT_DIRECTORY."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flex_testing_agent.evidence.redaction import redact_secrets


class EvidenceStore:
    """Write redacted JSON evidence for a single run."""

    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory
        self.run_directory.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload: Any) -> Path:
        """Write a redacted JSON artifact and return its path."""
        filename = name if name.endswith(".json") else f"{name}.json"
        path = self.run_directory / filename
        safe = redact_secrets(payload)
        path.write_text(
            json.dumps(safe, indent=2, default=str, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path
