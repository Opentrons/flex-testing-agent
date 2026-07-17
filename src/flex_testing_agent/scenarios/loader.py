"""Load scenario YAML metadata (not a YAML programming language)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ScenarioMetadata(BaseModel):
    """Versionable scenario metadata from YAML."""

    name: str
    description: str = ""
    requires: list[str] = Field(default_factory=list)
    risk_level: str = "READ_ONLY"
    max_duration_seconds: float = 120.0
    restore_baseline: bool = False


def load_scenario_metadata(path: Path) -> ScenarioMetadata:
    """Parse scenario metadata from a YAML file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Scenario file {path} must contain a YAML mapping.")
    return ScenarioMetadata.model_validate(data)
