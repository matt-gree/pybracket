from __future__ import annotations

from typing import Any

from .base import StandingsContext

__all__ = ["BuchholzTiebreaker"]


class BuchholzTiebreaker:
    """Buchholz: the sum of the win counts of all opponents faced.

    With `truncated=True`, the single lowest opponent score is dropped (median/truncated
    Buchholz), which reduces the impact of an opponent who later collapsed.
    """

    def __init__(self, truncated: bool = False) -> None:
        self.truncated = truncated
        self.name = "buchholz_truncated" if truncated else "buchholz"

    def score(self, participant_id: Any, ctx: StandingsContext) -> float:
        opponent_scores = [ctx.wins.get(opp, 0) for opp in ctx.opponents.get(participant_id, [])]
        if not opponent_scores:
            return 0.0
        if self.truncated and len(opponent_scores) > 1:
            opponent_scores.remove(min(opponent_scores))
        return float(sum(opponent_scores))

    def to_spec(self) -> dict[str, Any]:
        return {"type": "buchholz", "truncated": self.truncated}
