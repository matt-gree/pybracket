from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pybracket.errors import ValidationError
from pybracket.seeding.algorithms import (
    assert_protected_seeds,
    half_shift,
    inner_outer,
    pair_flip,
    reverse,
    reverse_half_shift,
    seed_slots,
    standard_bracket_positions,
)


def test_standard_positions_known_values() -> None:
    assert standard_bracket_positions(2) == [1, 2]
    assert standard_bracket_positions(4) == [1, 4, 2, 3]
    assert standard_bracket_positions(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert standard_bracket_positions(16) == [
        1, 16, 8, 9, 4, 13, 5, 12, 2, 15, 7, 10, 3, 14, 6, 11
    ]


def test_standard_positions_requires_power_of_two() -> None:
    with pytest.raises(ValidationError):
        standard_bracket_positions(6)


def test_ordering_methods() -> None:
    assert reverse([1, 2, 3, 4]) == [4, 3, 2, 1]
    assert half_shift([1, 2, 3, 4]) == [3, 4, 1, 2]
    assert reverse_half_shift([1, 2, 3, 4]) == [2, 1, 4, 3]
    assert pair_flip([1, 2, 3, 4]) == [2, 1, 4, 3]


def test_inner_outer_matches_positions() -> None:
    assert inner_outer(["a", "b", "c", "d"]) == ["a", "d", "b", "c"]


def test_seed_slots_pads_with_byes() -> None:
    slots = seed_slots([1, 2, 3], 4)
    assert slots == [1, None, 2, 3]  # seed 1 vs bye, seed 2 vs seed 3


@given(st.integers(min_value=1, max_value=64))
def test_seed_one_first_slot(n: int) -> None:
    size = 1 << (max(0, n - 1)).bit_length() if n > 1 else 1
    slots = seed_slots(list(range(1, n + 1)), size)
    assert slots[0] == 1


def test_assert_protected_seeds_passes_for_standard() -> None:
    positions = standard_bracket_positions(8)
    seed_at_slot = [p if p <= 8 else None for p in positions]
    assert_protected_seeds(seed_at_slot, 4, 8)  # no exception


def test_assert_protected_seeds_detects_collision() -> None:
    # Force seeds 1 and 2 into the same quarter.
    bad = [1, 2, 3, 4, 5, 6, 7, 8]
    with pytest.raises(ValidationError):
        assert_protected_seeds(bad, 4, 8)


def test_assert_protected_seeds_zero_is_noop() -> None:
    assert_protected_seeds([1, 2, 3, 4], 0, 4)  # no exception, nothing protected


def test_assert_protected_seeds_rejects_more_than_size() -> None:
    with pytest.raises(ValidationError):
        assert_protected_seeds([1, 2, 3, 4], protected=8, size=4)


def test_seed_slots_requires_power_of_two() -> None:
    with pytest.raises(ValidationError):
        seed_slots([1, 2, 3], 6)
