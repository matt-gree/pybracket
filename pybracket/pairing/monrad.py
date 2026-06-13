from __future__ import annotations

from typing import Any

from ..models.participant import Participant

__all__ = [
    "monrad_pairings",
    "rank_participants",
    "assign_bye",
    "pair_adjacent_with_backtrack",
]


def rank_participants(
    participants: list[Participant], scores: dict[Any, float]
) -> list[Participant]:
    """Rank by score descending, then by seed ascending (better seed breaks ties)."""
    return sorted(participants, key=lambda p: (-scores.get(p.id, 0.0), p.seed))


def assign_bye(
    ranked: list[Participant], had_bye: set[Any]
) -> tuple[list[Participant], Any | None]:
    """Remove the bye recipient: the lowest-ranked player who has not yet had a bye."""
    if len(ranked) % 2 == 0:
        return ranked, None
    for participant in reversed(ranked):
        if participant.id not in had_bye:
            remaining = [p for p in ranked if p.id != participant.id]
            return remaining, participant.id
    # Everyone already had a bye: give it to the lowest-ranked player.
    bye_id = ranked[-1].id
    return ranked[:-1], bye_id


def pair_adjacent_with_backtrack(
    order: list[Any], played: set[frozenset[Any]]
) -> list[tuple[Any, Any]] | None:
    """Pair an ordered list, each player with its nearest non-rematch partner; backtrack."""

    def solve(remaining: list[Any]) -> list[tuple[Any, Any]] | None:
        if not remaining:
            return []
        x = remaining[0]
        for idx in range(1, len(remaining)):
            y = remaining[idx]
            if frozenset((x, y)) in played:
                continue
            rest = remaining[1:idx] + remaining[idx + 1 :]
            sub = solve(rest)
            if sub is not None:
                return [(x, y), *sub]
        return None

    return solve(order)


def monrad_pairings(
    participants: list[Participant],
    scores: dict[Any, float],
    played: set[frozenset[Any]],
    had_bye: set[Any],
    allow_bye: bool = True,
) -> tuple[list[tuple[Any, Any]], Any | None]:
    """Monrad pairing: rank by standings and pair nearest neighbours, avoiding rematches."""
    ranked = rank_participants(participants, scores)
    bye_id: Any | None = None
    if len(ranked) % 2 == 1:
        if not allow_bye:
            raise ValueError("Odd number of players but byes are disabled.")
        ranked, bye_id = assign_bye(ranked, had_bye)

    order = [p.id for p in ranked]
    pairings = pair_adjacent_with_backtrack(order, played)
    if pairings is None:
        # No rematch-free pairing exists; fall back to nearest-neighbour ignoring history.
        pairings = [(order[i], order[i + 1]) for i in range(0, len(order), 2)]
    return pairings, bye_id
