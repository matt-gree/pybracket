from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import AdvancementType, BracketSide, MatchStatus
from .game import Game

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
    games: list[Game] = field(default_factory=list)
    # Per-game series log (empty when the match was reported with report_result).
    stats: dict[str, dict[Any, float]] = field(default_factory=dict)
    # Match-level stat contributions when no game log is kept: {stat_name: {participant_id: v}}.

    @property
    def series_score(self) -> tuple[int, int]:
        """Games won by (participant1, participant2) across the logged games."""
        p1, p2 = self.participant1_id, self.participant2_id
        w1 = sum(1 for g in self.games if g.winner_id == p1)
        w2 = sum(1 for g in self.games if g.winner_id == p2)
        return (w1, w2)
