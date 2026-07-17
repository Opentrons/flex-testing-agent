"""Capability risk levels for agent-ready allowlisting."""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    """Risk classification for harness capabilities."""

    READ_ONLY = "READ_ONLY"
    REVERSIBLE_MUTATION = "REVERSIBLE_MUTATION"
    DISRUPTIVE = "DISRUPTIVE"
    INSTALLATION = "INSTALLATION"
    DESTRUCTIVE = "DESTRUCTIVE"
    PHYSICAL_MOTION = "PHYSICAL_MOTION"
