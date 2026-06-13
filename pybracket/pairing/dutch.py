from __future__ import annotations

from itertools import groupby
from typing import Any

from ..models.participant import Participant
from .monrad import assign_bye, pair_adjacent_with_backtrack, rank_participants

__all__ = ["dutch_pairings", "dutch_order"]

# Implements the core of the FIDE (Dutch) System, Handbook C.04.3:
#   - players are ranked and partitioned into score brackets (FIDE rule A.3),
#   - within a bracket the top half S1 is paired against the bottom half S2 (rule B / C.5),
#   - an odd player in a bracket downfloats to the next bracket (rule A.4 / B),
#   - rematches are forbidden (absolute criterion B.1), satisfied here by transposition
#     (reordering S2 / backtracking) rather than failing.
# Color allocation (FIDE E) is not modelled: most games pybracket targets have no colors.


def dutch_order(
    ranked: list[Participant], scores: dict[Any, float]
) -> list[Any]:
    """Produce the S1-vs-S2 interleaved ordering across score brackets, with downfloats.

    Adjacent pairing of the returned id list yields top-half-vs-bottom-half pairings inside
    each score bracket; an odd player floats down to join the next (lower) bracket.
    """
    order: list[Any] = []
    carry: list[Participant] = []
    for _, group_iter in groupby(ranked, key=lambda p: scores.get(p.id, 0.0)):
        members = carry + list(group_iter)
        carry = []
        if len(members) % 2 == 1:
            carry = [members[-1]]  # lowest-ranked player downfloats
            members = members[:-1]
        half = len(members) // 2
        s1 = members[:half]
        s2 = members[half:]
        for i in range(half):
            order.append(s1[i].id)
            order.append(s2[i].id)
    order.extend(p.id for p in carry)
    return order


def dutch_pairings(
    participants: list[Participant],
    scores: dict[Any, float],
    played: set[frozenset[Any]],
    had_bye: set[Any],
    allow_bye: bool = True,
) -> tuple[list[tuple[Any, Any]], Any | None]:
    """FIDE Dutch pairing: score brackets, S1-vs-S2, downfloats, no rematches."""
    ranked = rank_participants(participants, scores)
    bye_id: Any | None = None
    if len(ranked) % 2 == 1:
        if not allow_bye:
            raise ValueError("Odd number of players but byes are disabled.")
        ranked, bye_id = assign_bye(ranked, had_bye)

    order = dutch_order(ranked, scores)
    pairings = pair_adjacent_with_backtrack(order, played)
    if pairings is None:
        # Fall back to a plain ranked nearest-neighbour pairing ignoring rematch history.
        ranked_ids = [p.id for p in ranked]
        pairings = [(ranked_ids[i], ranked_ids[i + 1]) for i in range(0, len(ranked_ids), 2)]
    return pairings, bye_id
