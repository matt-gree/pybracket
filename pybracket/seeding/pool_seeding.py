from __future__ import annotations

from typing import TypeVar

from ..models.participant import Participant
from ..utils.math import next_power_of_2
from .algorithms import seed_slots

T = TypeVar("T")

__all__ = [
    "pool_sizes",
    "snake_pool_assignment",
    "qualifier_seed_order",
    "qualifier_slot_order",
]


def pool_sizes(participant_count: int, num_pools: int) -> list[int]:
    """Pool sizes with extras distributed to the earliest pools (A before B)."""
    base = participant_count // num_pools
    extra = participant_count % num_pools
    return [base + (1 if i < extra else 0) for i in range(num_pools)]


def snake_pool_assignment(
    participants: list[Participant], num_pools: int
) -> list[list[Participant]]:
    """Serpentine pool assignment: 1->A, 2->B, ..., P->last, P+1->last, P+2->...->A."""
    ordered = sorted(participants, key=lambda p: p.seed)
    pools: list[list[Participant]] = [[] for _ in range(num_pools)]
    idx = 0
    forward = True
    for p in ordered:
        pools[idx].append(p)
        if forward:
            if idx == num_pools - 1:
                forward = False
            else:
                idx += 1
        else:
            if idx == 0:
                forward = True
            else:
                idx -= 1
    return pools


def qualifier_seed_order(
    ranked_by_pool: list[list[Participant]],
    advancement_count: int,
    snake_shuffle: bool,
) -> list[Participant]:
    """Global elimination seed order for pool qualifiers (rank-major, pool winners first).

    Without the shuffle this is rank-major in pool order. With the shuffle, deeper rank
    bands rotate their pool order so that same-pool qualifiers tend toward opposite sides.
    """
    num_pools = len(ranked_by_pool)
    order: list[Participant] = []
    for rank in range(advancement_count):
        pool_indices = list(range(num_pools))
        if snake_shuffle and rank % 2 == 1:
            # Rotate odd rank bands by half the pools so a pool's runner-up does not land
            # adjacent (in standard seeding) to that pool's winner.
            shift = num_pools // 2
            pool_indices = pool_indices[shift:] + pool_indices[:shift]
        for pool in pool_indices:
            if rank < len(ranked_by_pool[pool]):
                order.append(ranked_by_pool[pool][rank])
    return order


def qualifier_slot_order(
    ranked_by_pool: list[list[Participant]],
    advancement_count: int,
    snake_shuffle: bool,
) -> list[Participant | None]:
    """Bracket slot order (length = next power of two) for pool qualifiers.

    When `snake_shuffle` is set, a repair pass removes any first-round match that would pit
    two qualifiers from the same pool against each other (a guaranteed rematch), as long as
    a swap exists that does not create a new same-pool collision.
    """
    seed_order = qualifier_seed_order(ranked_by_pool, advancement_count, snake_shuffle)
    size = next_power_of_2(len(seed_order))
    slots: list[Participant | None] = seed_slots(seed_order, size)
    if snake_shuffle:
        _repair_first_round(slots, ranked_by_pool)
    return slots


def _repair_first_round(
    slots: list[Participant | None],
    ranked_by_pool: list[list[Participant]],
) -> None:
    pool_of = {
        p.id: i for i, pool in enumerate(ranked_by_pool) for p in pool
    }

    def same_pool(a: Participant | None, b: Participant | None) -> bool:
        if a is None or b is None:
            return False
        return pool_of.get(a.id) == pool_of.get(b.id)

    n = len(slots)
    for i in range(0, n, 2):
        a, b = slots[i], slots[i + 1]
        if not same_pool(a, b):
            continue
        # Find another slot j whose occupant we can swap into i+1 without creating a new
        # same-pool collision in either affected match.
        for j in range(0, n):
            if j == i or j == i + 1:
                continue
            partner = j - 1 if j % 2 == 1 else j + 1
            cand = slots[j]
            if cand is None:
                continue
            if same_pool(slots[i], cand):
                continue
            # Moving slots[i+1] (=b) into j and cand into i+1.
            if same_pool(b, slots[partner]) or same_pool(cand, slots[partner]):
                # cand vs partner is the j-match after swap; b takes cand's place.
                continue
            slots[i + 1], slots[j] = cand, b
            break
