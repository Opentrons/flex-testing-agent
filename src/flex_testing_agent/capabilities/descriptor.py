"""Agent-ready capability descriptors (metadata only in milestone 1)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from flex_testing_agent.models.risk import RiskLevel


class CapabilityDescriptor(BaseModel):
    """Describe an allowlisted harness capability for future agent use."""

    name: str
    description: str
    risk_level: RiskLevel
    mutates_robot: bool = False
    requires_cleanup: bool = False
    max_execution_time_seconds: float = 60.0
    required_robot_features: list[str] = Field(default_factory=list)
    evidence_produced: list[str] = Field(default_factory=list)
    input_schema: dict[str, object] = Field(default_factory=dict)
    output_schema: dict[str, object] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
