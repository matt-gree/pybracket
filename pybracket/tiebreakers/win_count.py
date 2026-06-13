from __future__ import annotations

from typing import Any

from .base import StandingsContext

__all__ = ["WinCountTiebreaker"]


class WinCountTiebreaker:
    """Number of match wins (forfeits and walkovers count as wins; byes do not)."""

    name = "win_count"

    def score(self, participant_id: Any, ctx: StandingsContext) -> float:
        return float(ctx.wins.get(participant_id, 0))

    def to_spec(self) -> dict[str, Any]:
        return {"type": self.name}
