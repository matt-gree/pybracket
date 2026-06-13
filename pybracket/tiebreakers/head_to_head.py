from __future__ import annotations

from typing import Any

from .base import StandingsContext

__all__ = ["HeadToHeadTiebreaker"]


class HeadToHeadTiebreaker:
    """Net head-to-head record (wins minus losses) against all faced opponents.

    Used as a secondary tiebreaker. `get_standings` additionally re-orders fully-tied
    cohorts by their head-to-head mini-league, which is the meaningful comparison.
    """

    name = "head_to_head"

    def score(self, participant_id: Any, ctx: StandingsContext) -> float:
        return float(sum(ctx.head_to_head.get(participant_id, {}).values()))

    def to_spec(self) -> dict[str, Any]:
        return {"type": self.name}
