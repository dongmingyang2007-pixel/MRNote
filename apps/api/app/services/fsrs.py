"""Simplified FSRS-4.5 spaced-repetition scheduler.

Public surface:
    schedule_next(difficulty, stability, rating, days_since_last_review)
        -> FSRSUpdate(difficulty, stability, next_interval_days)

Rating convention: 1=Again, 2=Hard, 3=Good, 4=Easy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_INITIAL_STABILITY = [0.4, 0.9, 2.3, 10.9]  # days, indexed by rating-1
_INITIAL_DIFFICULTY = [8.0, 6.0, 5.0, 3.0]

_RATING_FACTORS = {2: 0.5, 3: 1.0, 4: 1.3}  # for non-lapse ratings
_FACTOR_W = 3.0
_RETENTION_TARGET = 0.9

_MIN_STABILITY = 0.1  # days — avoid zero decay


@dataclass(frozen=True)
class FSRSUpdate:
    difficulty: float
    stability: float
    next_interval_days: int


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def schedule_next(
    *,
    difficulty: float,
    stability: float,
    rating: int,
    days_since_last_review: float,
) -> FSRSUpdate:
    """Advance a card's scheduling state after a review."""
    if rating < 1 or rating > 4:
        raise ValueError("rating must be 1-4")

    # New card — seed state from rating-indexed tables
    if stability <= 0.0:
        new_difficulty = _INITIAL_DIFFICULTY[rating - 1]
        new_stability = max(_MIN_STABILITY, _INITIAL_STABILITY[rating - 1])
        return FSRSUpdate(
            difficulty=new_difficulty,
            stability=new_stability,
            next_interval_days=max(1, round(new_stability)),
        )

    # Difficulty update
    difficulty_delta = (5 - rating) * 0.3
    new_difficulty = _clamp(difficulty + difficulty_delta, 1.0, 10.0)

    # Stability update
    if rating == 1:
        # Lapse — shrink stability aggressively
        new_stability = max(
            _MIN_STABILITY,
            stability * 0.2 * math.exp(-0.05 * new_difficulty),
        )
    else:
        retrievability = math.exp(
            math.log(_RETENTION_TARGET)
            * days_since_last_review
            / max(stability, _MIN_STABILITY)
        )
        factor = 1.0 + (
            math.exp(_FACTOR_W)
            * (11.0 - new_difficulty)
            * math.pow(stability, -0.3)
            * (math.exp((1.0 - retrievability) * 0.6) - 1.0)
            * _RATING_FACTORS[rating]
        )
        new_stability = max(_MIN_STABILITY, stability * factor)

    return FSRSUpdate(
        difficulty=new_difficulty,
        stability=new_stability,
        next_interval_days=max(1, round(new_stability)),
    )
