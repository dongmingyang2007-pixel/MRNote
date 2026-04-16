# ruff: noqa: E402
import math
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENV"] = "test"

import pytest
from app.services.fsrs import FSRSUpdate, schedule_next


def test_new_card_rating_good_seeds_from_table() -> None:
    out = schedule_next(difficulty=0, stability=0, rating=3, days_since_last_review=0)
    assert isinstance(out, FSRSUpdate)
    assert out.difficulty == 5.0
    assert math.isclose(out.stability, 2.3, rel_tol=1e-6)
    assert out.next_interval_days == 2


def test_new_card_rating_again_seeds_short() -> None:
    out = schedule_next(difficulty=0, stability=0, rating=1, days_since_last_review=0)
    assert out.difficulty == 8.0
    assert math.isclose(out.stability, 0.4, rel_tol=1e-6)
    assert out.next_interval_days == 1


def test_existing_card_rating_good_grows_stability() -> None:
    out = schedule_next(
        difficulty=5.0, stability=2.3, rating=3, days_since_last_review=2.0,
    )
    assert out.stability > 2.3
    assert out.next_interval_days >= 3


def test_existing_card_rating_again_shrinks_stability() -> None:
    out = schedule_next(
        difficulty=5.0, stability=10.0, rating=1, days_since_last_review=10.0,
    )
    assert out.stability < 2.5
    assert out.difficulty > 5.0  # difficulty rises on lapse


def test_rating_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        schedule_next(difficulty=5, stability=5, rating=0, days_since_last_review=1)
    with pytest.raises(ValueError):
        schedule_next(difficulty=5, stability=5, rating=5, days_since_last_review=1)
