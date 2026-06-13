from __future__ import annotations

import math

__all__ = [
    "next_power_of_2",
    "is_power_of_2",
    "recommend_swiss_rounds",
    "recommend_pool_count",
    "log2_int",
]


def next_power_of_2(n: int) -> int:
    """Smallest power of two greater than or equal to n (minimum 1)."""
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def is_power_of_2(n: int) -> bool:
    """True if n is a positive power of two."""
    return n >= 1 and (n & (n - 1)) == 0


def log2_int(n: int) -> int:
    """Exact integer log2 of a power of two."""
    if not is_power_of_2(n):
        raise ValueError(f"{n} is not a power of two")
    return n.bit_length() - 1


def recommend_swiss_rounds(participant_count: int) -> int:
    """Recommended Swiss round count: ceil(log2(n))."""
    if participant_count < 2:
        return 0
    return math.ceil(math.log2(participant_count))


def recommend_pool_count(participant_count: int, target_pool_size: int = 4) -> int:
    """Recommended number of pools so each pool is roughly target_pool_size."""
    if participant_count < 1:
        return 0
    if target_pool_size < 1:
        raise ValueError("target_pool_size must be >= 1")
    return max(1, round(participant_count / target_pool_size))
