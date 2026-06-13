from __future__ import annotations

import pytest
from pybracket import next_power_of_2, recommend_pool_count, recommend_swiss_rounds
from pybracket.utils.math import is_power_of_2, log2_int


@pytest.mark.parametrize(
    "n,expected",
    [(0, 1), (1, 1), (2, 2), (3, 4), (4, 4), (5, 8), (8, 8), (9, 16), (17, 32)],
)
def test_next_power_of_2(n: int, expected: int) -> None:
    assert next_power_of_2(n) == expected


@pytest.mark.parametrize(
    "n,expected",
    [(1, True), (2, True), (4, True), (1024, True), (0, False), (3, False), (6, False)],
)
def test_is_power_of_2(n: int, expected: bool) -> None:
    assert is_power_of_2(n) is expected


def test_log2_int_exact() -> None:
    assert log2_int(1) == 0
    assert log2_int(8) == 3
    assert log2_int(1024) == 10


def test_log2_int_rejects_non_power_of_two() -> None:
    with pytest.raises(ValueError):
        log2_int(6)


@pytest.mark.parametrize(
    "n,expected",
    [(0, 0), (1, 0), (2, 1), (3, 2), (4, 2), (7, 3), (8, 3), (16, 4), (32, 5), (33, 6)],
)
def test_recommend_swiss_rounds(n: int, expected: int) -> None:
    # SPEC: recommended Swiss round count is ceil(log2(n)); below 2 players there is no round.
    assert recommend_swiss_rounds(n) == expected


def test_recommend_pool_count_default_target() -> None:
    assert recommend_pool_count(16) == 4  # round(16 / 4)
    assert recommend_pool_count(15) == 4  # round(3.75)
    assert recommend_pool_count(10) == 2  # round(2.5) -> banker's rounding to 2


def test_recommend_pool_count_custom_target() -> None:
    assert recommend_pool_count(24, target_pool_size=6) == 4
    assert recommend_pool_count(20, target_pool_size=5) == 4


def test_recommend_pool_count_floor_is_one() -> None:
    # Even a tiny field gets at least one pool.
    assert recommend_pool_count(2, target_pool_size=4) == 1


def test_recommend_pool_count_zero_participants() -> None:
    assert recommend_pool_count(0) == 0


def test_recommend_pool_count_rejects_bad_target() -> None:
    with pytest.raises(ValueError):
        recommend_pool_count(16, target_pool_size=0)
