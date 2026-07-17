"""Safety gates for mutating and dry-run operations."""

from __future__ import annotations

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel


class MutationDeniedError(RuntimeError):
    """Raised when a mutating capability is blocked by policy."""


MUTATING_RISKS = frozenset(
    {
        RiskLevel.REVERSIBLE_MUTATION,
        RiskLevel.DISRUPTIVE,
        RiskLevel.INSTALLATION,
        RiskLevel.DESTRUCTIVE,
        RiskLevel.PHYSICAL_MOTION,
    }
)


def ensure_mutation_allowed(
    settings: Settings,
    *,
    risk_level: RiskLevel,
    capability_name: str,
) -> None:
    """Reject mutating capabilities unless ALLOW_MUTATIONS is true.

    Dry-run also blocks mutations. Physical motion is always rejected in
    milestone 1 regardless of settings.
    """
    if risk_level == RiskLevel.PHYSICAL_MOTION:
        raise MutationDeniedError(
            f"Capability {capability_name!r} requires physical motion, "
            "which is out of scope for this harness milestone."
        )
    if risk_level not in MUTATING_RISKS:
        return
    if settings.dry_run:
        raise MutationDeniedError(
            f"Capability {capability_name!r} is mutating and blocked by DRY_RUN=true."
        )
    if not settings.allow_mutations:
        raise MutationDeniedError(
            f"Capability {capability_name!r} is mutating and blocked because "
            "ALLOW_MUTATIONS=false."
        )
