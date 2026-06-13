from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from ..errors import ValidationError
from ..utils.math import is_power_of_2, next_power_of_2

# Seed-ordering methods ported from brackets-manager.js src/ordering.ts (MIT).
# Source comment there: superior double-elimination losers-bracket seeding (tl.net).

T = TypeVar("T")

__all__ = [
    "natural",
    "reverse",
    "half_shift",
    "reverse_half_shift",
    "pair_flip",
    "inner_outer",
    "ORDERINGS",
    "standard_bracket_positions",
    "seed_slots",
    "protected_seed_order",
    "assert_protected_seeds",
]


def natural(array: list[T]) -> list[T]:
    return list(array)


def reverse(array: list[T]) -> list[T]:
    return list(reversed(array))


def half_shift(array: list[T]) -> list[T]:
    half = len(array) // 2
    return [*array[half:], *array[:half]]


def reverse_half_shift(array: list[T]) -> list[T]:
    half = len(array) // 2
    return [*list(reversed(array[:half])), *list(reversed(array[half:]))]


def pair_flip(array: list[T]) -> list[T]:
    result: list[T] = []
    for i in range(0, len(array), 2):
        result.append(array[i + 1])
        result.append(array[i])
    return result


def standard_bracket_positions(size: int) -> list[int]:
    """Standard (inner-outer) bracket seed positions for a power-of-two size.

    Returns 1-indexed seed numbers in slot order, e.g. size 8 -> [1,8,4,5,2,7,3,6].
    Guarantees the top seeds can only meet in the latest round their seeding implies.
    """
    if not is_power_of_2(size):
        raise ValidationError(f"Bracket size must be a power of two, got {size}.")
    if size == 1:
        return [1]
    positions: list[int] = [1, 2]
    while len(positions) < size:
        block = len(positions) * 2
        nxt: list[int] = []
        for pos in positions:
            nxt.append(pos)
            nxt.append(block + 1 - pos)
        positions = nxt
    return positions


def inner_outer(array: list[T]) -> list[T]:
    """Reorder a power-of-two-sized array into standard bracket slot order."""
    if len(array) <= 2:
        return list(array)
    positions = standard_bracket_positions(len(array))
    return [array[pos - 1] for pos in positions]


ORDERINGS = {
    "natural": natural,
    "reverse": reverse,
    "half_shift": half_shift,
    "reverse_half_shift": reverse_half_shift,
    "pair_flip": pair_flip,
    "inner_outer": inner_outer,
}


def seed_slots(seeded: Sequence[T | None], size: int) -> list[T | None]:
    """Place a seed-ordered list (index 0 = seed 1) into standard bracket slots of `size`.

    `seeded` should already be sorted by seed. Missing seeds (slots beyond the field) are
    passed in as None and become byes. The slot at position i holds the participant whose
    natural seed is standard_bracket_positions(size)[i].
    """
    if not is_power_of_2(size):
        raise ValidationError(f"Bracket size must be a power of two, got {size}.")
    padded: list[T | None] = list(seeded) + [None] * (size - len(seeded))
    positions = standard_bracket_positions(size)
    return [padded[pos - 1] for pos in positions]


def protected_seed_order(seeded: Sequence[T | None], size: int) -> list[T | None]:
    """Standard bracket ordering; inner-outer placement inherently protects top seeds."""
    return seed_slots(seeded, size)


def assert_protected_seeds(slot_order: list[int | None], protected: int, size: int) -> None:
    """Verify the top `protected` seeds land in distinct equal sections of the bracket.

    `slot_order` is a list of seed numbers (1-indexed) or None per bracket slot. With
    `protected=4` and size 8, seeds 1-4 must each be in a different quarter so they cannot
    meet before the semifinals.
    """
    if protected <= 0:
        return
    if protected > size:
        raise ValidationError("protected_seeds cannot exceed the bracket size.")
    sections = next_power_of_2(protected)
    section_size = size // sections
    seen_sections: dict[int, int] = {}
    for slot_index, seed in enumerate(slot_order):
        if seed is None or seed > protected:
            continue
        section = slot_index // section_size
        if section in seen_sections:
            raise ValidationError(
                f"Protected seeds {seen_sections[section]} and {seed} share a bracket section."
            )
        seen_sections[section] = seed
