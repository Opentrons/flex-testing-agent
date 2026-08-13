"""Safe LPC-like jog geometry (no robot I/O).

Coordinates are millimetres relative to the approach pose (well A1 top plus
``approach_z_mm``). Origin is that pose. +Z is away from the deck.

KansasFLEX uses a virtual tiprack on empty slot C2. The physical deck is
therefore well below the virtual well top. The box never allows negative Z
relative to approach, so the pipette never moves closer to the deck than the
high approach. XY is biased into the 96-well grid from A1 (back-left of the
labware) so jogs stay over the virtual rack, not toward trash A3 or HS D1.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from pydantic import BaseModel, Field

AXES: tuple[str, ...] = ("x", "y", "z")
# LPC UI uses 0.1 / 1 / 10 mm. Skip 10 mm: the safe box is smaller than that.
DEFAULT_STEP_SIZES_MM: tuple[float, ...] = (0.1, 0.5, 1.0, 2.0)
DEFAULT_JOG_COUNT = 80
MAX_JOG_COUNT = 400
DEFAULT_RNG_SEED = 42
DEFAULT_SAVE_EVERY = 10


@dataclass(frozen=True, slots=True)
class AxisBounds:
    """Inclusive millimetre limits on one axis relative to approach."""

    min_mm: float
    max_mm: float

    def contains(self, value: float) -> bool:
        return self.min_mm - 1e-9 <= value <= self.max_mm + 1e-9


@dataclass(frozen=True, slots=True)
class SafeJogBox:
    """Axis-aligned box relative to the LPC approach pose."""

    x: AxisBounds
    y: AxisBounds
    z: AxisBounds

    def contains(self, x: float, y: float, z: float) -> bool:
        return self.x.contains(x) and self.y.contains(y) and self.z.contains(z)


# A1 is back-left of a 96 tiprack: +X toward H, -Y toward A12. Tiny margins
# the other way so we do not walk off the labware edge.
DEFAULT_SAFE_BOX = SafeJogBox(
    x=AxisBounds(min_mm=-2.0, max_mm=12.0),
    y=AxisBounds(min_mm=-12.0, max_mm=2.0),
    z=AxisBounds(min_mm=0.0, max_mm=20.0),
)


class PlannedJog(BaseModel):
    """One ``moveRelative`` step that stays inside the box."""

    index: int
    axis: str
    distance_mm: float
    x_after: float
    y_after: float
    z_after: float
    save_position: bool = False


class JogPlan(BaseModel):
    """Reproducible random-walk plan plus return-to-approach moves."""

    rng_seed: int
    jog_count: int
    box: dict[str, dict[str, float]]
    step_sizes_mm: list[float]
    jogs: list[PlannedJog] = Field(default_factory=list)
    return_jogs: list[PlannedJog] = Field(default_factory=list)
    rejected_candidates: int = 0
    final_x: float = 0.0
    final_y: float = 0.0
    final_z: float = 0.0


class JogLatencyStats(BaseModel):
    """Aggregate latency for a named group of timed jogs."""

    name: str
    count: int
    mean_seconds: float
    p50_seconds: float
    p95_seconds: float
    max_seconds: float
    min_seconds: float


def default_safe_box() -> SafeJogBox:
    """Return the KansasFLEX C2 / A1 high-Z box."""
    return DEFAULT_SAFE_BOX


def _bounds_dict(box: SafeJogBox) -> dict[str, dict[str, float]]:
    return {
        "x": {"min_mm": box.x.min_mm, "max_mm": box.x.max_mm},
        "y": {"min_mm": box.y.min_mm, "max_mm": box.y.max_mm},
        "z": {"min_mm": box.z.min_mm, "max_mm": box.z.max_mm},
    }


def _snap(value: float) -> float:
    """Collapse float dust so the tracker does not drift below zero."""
    return 0.0 if abs(value) < 1e-9 else value


def plan_random_jogs(
    *,
    jog_count: int = DEFAULT_JOG_COUNT,
    rng_seed: int = DEFAULT_RNG_SEED,
    box: SafeJogBox | None = None,
    step_sizes_mm: tuple[float, ...] = DEFAULT_STEP_SIZES_MM,
    save_every: int = DEFAULT_SAVE_EVERY,
) -> JogPlan:
    """Build a bounded random walk that never leaves *box*.

    Z relative to approach is never negative (never toward the deck).
    """
    if jog_count < 1 or jog_count > MAX_JOG_COUNT:
        raise ValueError(f"jog_count must be 1..{MAX_JOG_COUNT}, got {jog_count}")
    if save_every < 0:
        raise ValueError("save_every must be >= 0")
    safe = box or DEFAULT_SAFE_BOX
    if safe.z.min_mm < -1e-9:
        raise ValueError("safe box z.min_mm must be >= 0 (never jog toward deck)")
    rng = random.Random(rng_seed)
    x = y = z = 0.0
    jogs: list[PlannedJog] = []
    rejected = 0
    max_attempts = jog_count * 40
    attempts = 0
    while len(jogs) < jog_count and attempts < max_attempts:
        attempts += 1
        axis = rng.choice(AXES)
        step = rng.choice(step_sizes_mm)
        delta = rng.choice((-1.0, 1.0)) * step
        trial_x, trial_y, trial_z = x, y, z
        if axis == "x":
            trial_x = x + delta
        elif axis == "y":
            trial_y = y + delta
        else:
            trial_z = z + delta
        if not safe.contains(trial_x, trial_y, trial_z):
            rejected += 1
            continue
        x, y, z = _snap(trial_x), _snap(trial_y), _snap(trial_z)
        index = len(jogs)
        save = save_every > 0 and (index + 1) % save_every == 0
        jogs.append(
            PlannedJog(
                index=index,
                axis=axis,
                distance_mm=delta,
                x_after=x,
                y_after=y,
                z_after=z,
                save_position=save,
            )
        )
    if len(jogs) < jog_count:
        raise RuntimeError(
            f"could only plan {len(jogs)}/{jog_count} in-box jogs "
            f"(rejected={rejected}); widen the box or reduce step sizes"
        )
    return_jogs: list[PlannedJog] = []
    for axis, current in (("x", x), ("y", y), ("z", z)):
        if abs(current) < 1e-9:
            continue
        delta = -current
        if axis == "x":
            x = 0.0
        elif axis == "y":
            y = 0.0
        else:
            z = 0.0
        return_jogs.append(
            PlannedJog(
                index=len(return_jogs),
                axis=axis,
                distance_mm=delta,
                x_after=x,
                y_after=y,
                z_after=z,
                save_position=False,
            )
        )
    return JogPlan(
        rng_seed=rng_seed,
        jog_count=len(jogs),
        box=_bounds_dict(safe),
        step_sizes_mm=list(step_sizes_mm),
        jogs=jogs,
        return_jogs=return_jogs,
        rejected_candidates=rejected,
        final_x=jogs[-1].x_after if jogs else 0.0,
        final_y=jogs[-1].y_after if jogs else 0.0,
        final_z=jogs[-1].z_after if jogs else 0.0,
    )


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in 0..1) of *values*."""
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 1:
        return max(values)
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def latency_stats(name: str, durations: list[float]) -> JogLatencyStats:
    """Summarize a list of positive durations."""
    if not durations:
        return JogLatencyStats(
            name=name,
            count=0,
            mean_seconds=0.0,
            p50_seconds=0.0,
            p95_seconds=0.0,
            max_seconds=0.0,
            min_seconds=0.0,
        )
    return JogLatencyStats(
        name=name,
        count=len(durations),
        mean_seconds=sum(durations) / len(durations),
        p50_seconds=percentile(durations, 0.50),
        p95_seconds=percentile(durations, 0.95),
        max_seconds=max(durations),
        min_seconds=min(durations),
    )
