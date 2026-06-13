from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import AdvancementType, BracketSide, MatchStatus

__all__ = ["Match"]


@dataclass
class Match:
    id: int
    round_number: int
    bracket_side: BracketSide
    participant1_id: Any | None  # None = slot not yet filled (PENDING) or BYE
    participant2_id: Any | None
    winner_id: Any | None
    loser_id: Any | None
    advancement_type: AdvancementType | None
    next_winner_match_id: int | None  # Where winner advances to
    next_loser_match_id: int | None  # Where loser drops (double elim only)
    status: MatchStatus
    best_of: int = 1  # BO1 default; TO can set per match or per round
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata: caller attaches game IDs, timestamps, scores, etc.
    # Library never reads metadata. It is returned as-is in unwind signals.
