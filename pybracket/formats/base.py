from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..models.bracket import Bracket
from ..models.enums import BracketSide, MatchStatus
from ..models.match import Match
from ..models.participant import Participant

__all__ = ["BaseFormat", "IdGen", "make_match", "build_standard_bracket"]


class IdGen:
    """Monotonic match-id generator."""

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def __call__(self) -> int:
        value = self._next
        self._next += 1
        return value


def make_match(
    match_id: int,
    round_number: int,
    bracket_side: BracketSide,
    participant1_id: Any | None = None,
    participant2_id: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> Match:
    return Match(
        id=match_id,
        round_number=round_number,
        bracket_side=bracket_side,
        participant1_id=participant1_id,
        participant2_id=participant2_id,
        winner_id=None,
        loser_id=None,
        advancement_type=None,
        next_winner_match_id=None,
        next_loser_match_id=None,
        status=MatchStatus.PENDING,
        metadata=metadata if metadata is not None else {},
    )


def build_standard_bracket(
    ordered_slots: list[Participant | None],
    id_gen: Callable[[], int],
    bracket_side: BracketSide = BracketSide.WINNERS,
    max_rounds: int | None = None,
) -> tuple[list[Match], list[list[int]], int]:
    """Build a single-elimination tree from ordered slots (length = power of two).

    Returns (matches, round_match_ids, final_match_id). `round_match_ids[r]` lists the match
    ids of round r+1 in order, which doubles as the per-round loser provenance for the LB.

    ``max_rounds`` caps the number of rounds emitted (for a *truncated* / qualifier bracket
    that stops once a top-N is decided). The last emitted round's winners have no next match.
    """
    size = len(ordered_slots)
    num_rounds = size.bit_length() - 1  # log2(size)
    if max_rounds is not None:
        num_rounds = min(num_rounds, max_rounds)
    by_id: dict[int, Match] = {}
    matches: list[Match] = []
    round_match_ids: list[list[int]] = []

    # Round 1: concrete participants from the seeded slots.
    first: list[int] = []
    for i in range(0, size, 2):
        p1 = ordered_slots[i]
        p2 = ordered_slots[i + 1]
        m = make_match(
            id_gen(),
            1,
            bracket_side,
            participant1_id=p1.id if p1 is not None else None,
            participant2_id=p2.id if p2 is not None else None,
        )
        matches.append(m)
        by_id[m.id] = m
        first.append(m.id)
    round_match_ids.append(first)

    # Subsequent rounds: winners of two prior matches meet.
    prev = first
    for r in range(2, num_rounds + 1):
        current: list[int] = []
        for k in range(len(prev) // 2):
            m = make_match(id_gen(), r, bracket_side)
            matches.append(m)
            by_id[m.id] = m
            current.append(m.id)
            by_id[prev[2 * k]].next_winner_match_id = m.id
            by_id[prev[2 * k + 1]].next_winner_match_id = m.id
        round_match_ids.append(current)
        prev = current

    final_id = prev[0]
    return matches, round_match_ids, final_id


class BaseFormat(ABC):
    """Abstract base for bracket formats. Concrete formats expose module-level generate_*()."""

    format_name: str

    @abstractmethod
    def generate(self, participants: list[Participant], **kwargs: Any) -> Bracket:
        """Produce a fully-initialised Bracket for this format."""
        raise NotImplementedError
