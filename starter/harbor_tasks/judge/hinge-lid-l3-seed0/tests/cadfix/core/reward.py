"""Data-driven reward. Generic: knows nothing about any scenario; the scenario supplies the numbers.

reward = 0                                              if any gate fails
       = progress_weight * progress                     if the objective is not met (progress in [0, 1])
       = met_base + sum(weights[k] * scores[k])         if the objective is met (scores in [0, 1])
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def linear_score(x: float, full: float, zero: float) -> float:
    """1 for x <= full, 0 for x >= zero, linear in between (full < zero)."""
    if x <= full:
        return 1.0
    if x >= zero:
        return 0.0
    return (zero - x) / (zero - full)


def progress(value: float, initial: float, target: float) -> float:
    """(value - initial) / (target - initial) clipped to [0, 1]."""
    if target == initial:
        return 1.0 if value >= target else 0.0
    return min(1.0, max(0.0, (value - initial) / (target - initial)))


def ratio_score(value: float, reference: float, full_factor: float, zero_factor: float) -> float:
    """Minimal-change score: 1 up to full_factor x reference, linear to 0 at zero_factor x reference."""
    return linear_score(value / reference, full_factor, zero_factor)


def sweep_progress(ok_until: float | None, initial: float | None, target: float, min_clearance: float,
                   required_clearance: float, any_overlap: bool, angle_weight: float = 0.5) -> float:
    """Progress of a joint sweep objective: angle_weight * angle progress + (1 - angle_weight) * clearance
    progress. Angle progress = (largest angle up to which the rules hold - initial) / (target - initial),
    clipped; clearance progress = clip(min_clearance / required_clearance, 0, 1), 0 if anything overlaps."""
    a = progress(ok_until if ok_until is not None else -math.inf, initial if initial is not None else 0.0, target)
    c = 0.0 if any_overlap else min(1.0, max(0.0, min_clearance / required_clearance))
    return angle_weight * a + (1.0 - angle_weight) * c


@dataclass(frozen=True)
class RewardPolicy:
    progress_weight: float
    met_base: float
    weights: dict = field(default_factory=dict)

    def reward(self, gates_ok: bool, objective_met: bool, progress: float, scores: dict) -> float:
        if not gates_ok:
            return 0.0
        if not objective_met:
            return round(self.progress_weight * min(1.0, max(0.0, progress)), 6)
        return round(self.met_base + sum(w * scores[k] for k, w in self.weights.items()), 6)
