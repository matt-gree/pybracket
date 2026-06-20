from __future__ import annotations

from typing import Any

from ..models.match import Match
from .base import StandingsContext

__all__ = ["MiniLeagueTiebreaker"]


class MiniLeagueTiebreaker:
    """Relational tiebreaker: rank a tied cohort by a sub-table of only their mutual results.

    Run as a terminal cohort reorder (never a scalar sort-key term). For a tied group it builds
    a standings sub-table from just the matches played between members of the group and ranks by
    match wins within it — the standard "results among the tied teams" tiebreaker.
    """

    name = "mini_league"

    def score(self, participant_id: Any, ctx: StandingsContext) -> float:
        # Not a scalar contributor; ranking happens per cohort via cohort_value.
        return 0.0

    def cohort_value(
        self,
        participant_id: Any,
        cohort: set[Any],
        ctx: StandingsContext,
        matches: list[Match],
    ) -> float:
        mutual = [
            m
            for m in matches
            if m.participant1_id in cohort and m.participant2_id in cohort
        ]
        sub = StandingsContext(mutual, list(cohort))
        return float(sub.wins.get(participant_id, 0))

    def to_spec(self) -> dict[str, Any]:
        return {"type": self.name}
