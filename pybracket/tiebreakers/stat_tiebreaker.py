from __future__ import annotations

from typing import Any

from ..models.participant import Participant
from .base import StandingsContext

__all__ = ["StatTiebreaker"]


class StatTiebreaker:
    """Tiebreaker keyed on a caller-defined value in `Participant.stats`.

    The library never references game-specific stat names itself — the caller chooses the
    key (e.g. 'run_differential', 'glicko_rating'). Missing values fall back to `default`.
    """

    def __init__(
        self,
        stat_key: str,
        higher_is_better: bool = True,
        default: float = 0.0,
    ) -> None:
        self.stat_key = stat_key
        self.higher_is_better = higher_is_better
        self.default = default
        self.name = f"stat:{stat_key}"
        self._participants: dict[Any, Participant] = {}

    def bind(self, participants: list[Participant]) -> StatTiebreaker:
        """Attach the participant list so stats can be looked up by id."""
        self._participants = {p.id: p for p in participants}
        return self

    def score(self, participant_id: Any, ctx: StandingsContext) -> float:
        participant = self._participants.get(participant_id)
        raw = self.default
        if participant is not None:
            raw = float(participant.stats.get(self.stat_key, self.default))
        return raw if self.higher_is_better else -raw

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "stat",
            "stat_key": self.stat_key,
            "higher_is_better": self.higher_is_better,
            "default": self.default,
        }
