from __future__ import annotations

import pytest
from pybracket.seeding.pool_seeding import (
    _repair_first_round,
    pool_sizes,
    qualifier_seed_order,
    qualifier_slot_order,
    snake_pool_assignment,
)

from tests.helpers import make_participants


@pytest.mark.parametrize(
    "n,pools,expected",
    [
        (8, 2, [4, 4]),
        (8, 4, [2, 2, 2, 2]),
        (10, 4, [3, 3, 2, 2]),
        (7, 2, [4, 3]),
    ],
)
def test_pool_sizes(n: int, pools: int, expected: list[int]) -> None:
    assert pool_sizes(n, pools) == expected


def test_snake_assignment() -> None:
    pools = snake_pool_assignment(make_participants(8), 4)
    seeds = [[p.seed for p in pool] for pool in pools]
    # 1->A, 2->B, 3->C, 4->D, 5->D, 6->C, 7->B, 8->A
    assert seeds == [[1, 8], [2, 7], [3, 6], [4, 5]]


def test_qualifier_seed_order_winners_first() -> None:
    participants = make_participants(8)
    pools = snake_pool_assignment(participants, 4)
    # Pool winners (rank 0) are the lowest seed in each pool.
    ranked = [sorted(pool, key=lambda p: p.seed) for pool in pools]
    order = qualifier_seed_order(ranked, advancement_count=2, snake_shuffle=False)
    # First four are the four pool winners.
    assert [p.seed for p in order[:4]] == [1, 2, 3, 4]


def test_qualifier_slot_order_no_same_pool_round_one() -> None:
    participants = make_participants(16)
    pools = snake_pool_assignment(participants, 4)
    ranked = [sorted(pool, key=lambda p: p.seed) for pool in pools]
    pool_of = {p.id: i for i, pool in enumerate(pools) for p in pool}
    slots = qualifier_slot_order(ranked, advancement_count=2, snake_shuffle=True)
    for i in range(0, len(slots), 2):
        a, b = slots[i], slots[i + 1]
        if a is not None and b is not None:
            assert pool_of[a.id] != pool_of[b.id]


def test_repair_first_round_breaks_up_same_pool_collision() -> None:
    # Directly exercise the rematch-avoidance swap: slots[0] and slots[1] are both from
    # pool 0, which is a guaranteed first-round rematch the repair pass must break up.
    p = make_participants(6)
    ranked_by_pool = [[p[0], p[1]], [p[2], p[3]], [p[4], p[5]]]
    pool_of = {part.id: i for i, pool in enumerate(ranked_by_pool) for part in pool}
    slots = [p[0], p[1], p[2], p[4], p[3], p[5]]  # match (p0, p1) is a pool-0 collision
    _repair_first_round(slots, ranked_by_pool)
    for i in range(0, len(slots), 2):
        a, b = slots[i], slots[i + 1]
        if a is not None and b is not None:
            assert pool_of[a.id] != pool_of[b.id]
    # No participant was lost or duplicated by the swap.
    assert {s.id for s in slots if s is not None} == {part.id for part in p}
