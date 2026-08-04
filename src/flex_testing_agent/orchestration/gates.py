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

    Dry-run also blocks mutations. ``PHYSICAL_MOTION`` is allowed only when
    mutations are enabled (operator-requested capabilities such as
    ``seed_runs``); it is never the default path.
    """
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
