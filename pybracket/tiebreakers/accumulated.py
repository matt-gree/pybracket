from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ValidationError
from .base import StandingsContext

__all__ = ["AccumulatedTiebreaker"]

_AGGREGATIONS = frozenset({"for", "against", "diff", "count", "avg"})


@dataclass(frozen=True)
class AccumulatedTiebreaker:
    """A scalar tiebreaker over an accumulated input, with a chosen aggregation.

    The library names no stat: ``input`` is either a built-in derived input the engine computes
    from results (``"wins"`` -> wins/losses, ``"games"`` -> games_won/games_lost, ``"draws"``,
    ``"points"`` when a PointsSystem is set) or any caller stat name (e.g. ``"runs"``). ``agg``
    selects the aggregation:

    - ``for``     — the participant's own total
    - ``against`` — opponents' total in shared games/matches
    - ``diff``    — ``for - against``
    - ``count``   — games (or match-level results) played
    - ``avg``     — ``for / count`` (0 when nothing has been played)

    ``higher_is_better=False`` flips the direction (e.g. fewest goals against).
    """

    input: str
    agg: str = "diff"
    higher_is_better: bool = True

    def __post_init__(self) -> None:
        if self.agg not in _AGGREGATIONS:
            raise ValidationError(
                f"agg must be one of {sorted(_AGGREGATIONS)}, got {self.agg!r}."
            )

    @property
    def name(self) -> str:
        return f"acc:{self.input}:{self.agg}"

    def _for_against(self, participant_id: Any, ctx: StandingsContext) -> tuple[float, float]:
        if self.input == "wins":
            return float(ctx.wins.get(participant_id, 0)), float(ctx.losses.get(participant_id, 0))
        if self.input == "games":
            return (
                float(ctx.games_won.get(participant_id, 0)),
                float(ctx.games_lost.get(participant_id, 0)),
            )
        if self.input == "draws":
            return float(ctx.draws.get(participant_id, 0)), 0.0
        if self.input == "points":
            return ctx.points.get(participant_id, 0.0), 0.0
        return (
            ctx.stat_for.get(participant_id, {}).get(self.input, 0.0),
            ctx.stat_against.get(participant_id, {}).get(self.input, 0.0),
        )

    def score(self, participant_id: Any, ctx: StandingsContext) -> float:
        own, opp = self._for_against(participant_id, ctx)
        count = ctx.count.get(participant_id, 0)
        if self.agg == "for":
            raw = own
        elif self.agg == "against":
            raw = opp
        elif self.agg == "diff":
            raw = own - opp
        elif self.agg == "count":
            raw = float(count)
        else:  # avg
            raw = own / count if count else 0.0
        return raw if self.higher_is_better else -raw

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "accumulated",
            "input": self.input,
            "agg": self.agg,
            "higher_is_better": self.higher_is_better,
        }
