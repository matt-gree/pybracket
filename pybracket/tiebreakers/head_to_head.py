from __future__ import annotations

from typing import Any

from ..models.match import Match
from .base import StandingsContext

__all__ = ["HeadToHeadTiebreaker"]


class HeadToHeadTiebreaker:
    """Relational tiebreaker: rank a tied cohort by net head-to-head record among its members.

    Run as a terminal cohort reorder (never a scalar sort-key term) — head-to-head only means
    something *among the tied participants*, and can be cyclic, so it cannot be a global score.
    ``score`` still exposes the net record against all faced opponents for callers that want it.
    """

    name = "head_to_head"

    def score(self, participant_id: Any, ctx: StandingsContext) -> float:
        return float(sum(ctx.head_to_head.get(participant_id, {}).values()))

    def cohort_value(
        self,
        participant_id: Any,
        cohort: set[Any],
        ctx: StandingsContext,
        matches: list[Match],
    ) -> float:
        return float(
            sum(
                v
                for opp, v in ctx.head_to_head.get(participant_id, {}).items()
                if opp in cohort
            )
        )

    def to_spec(self) -> dict[str, Any]:
        return {"type": self.name}
