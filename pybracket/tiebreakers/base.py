from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models.enums import AdvancementType, MatchStatus
from ..models.match import Match

__all__ = ["StandingsContext", "Tiebreaker"]

_REAL = frozenset(
    {AdvancementType.RESULT, AdvancementType.FORFEIT, AdvancementType.WALKOVER}
)


class StandingsContext:
    """Precomputed win/loss/opponent data for a group of participants."""

    def __init__(self, matches: list[Match], participant_ids: list[Any]) -> None:
        self.participant_ids = list(participant_ids)
        self.wins: dict[Any, int] = dict.fromkeys(participant_ids, 0)
        self.losses: dict[Any, int] = dict.fromkeys(participant_ids, 0)
        self.opponents: dict[Any, list[Any]] = {pid: [] for pid in participant_ids}
        self.head_to_head: dict[Any, dict[Any, int]] = {pid: {} for pid in participant_ids}
        self.adv_counts: dict[Any, dict[AdvancementType, int]] = {
            pid: {} for pid in participant_ids
        }
        self._ingest(matches)

    def _bump_adv(self, pid: Any, adv: AdvancementType) -> None:
        counts = self.adv_counts[pid]
        counts[adv] = counts.get(adv, 0) + 1

    def _ingest(self, matches: list[Match]) -> None:
        known = set(self.participant_ids)
        for m in matches:
            if m.status is MatchStatus.BYE and m.winner_id in known:
                self._bump_adv(m.winner_id, AdvancementType.BYE)
                continue
            if m.status is not MatchStatus.COMPLETED:
                continue
            adv = m.advancement_type
            if adv not in _REAL or adv is None:
                continue
            winner, loser = m.winner_id, m.loser_id
            if winner in known:
                self.wins[winner] += 1
                self._bump_adv(winner, adv)
                if loser is not None:
                    self.opponents[winner].append(loser)
                    self.head_to_head[winner][loser] = (
                        self.head_to_head[winner].get(loser, 0) + 1
                    )
            if loser in known:
                self.losses[loser] += 1
                if winner is not None:
                    self.opponents[loser].append(winner)
                    self.head_to_head[loser][winner] = (
                        self.head_to_head[loser].get(winner, 0) - 1
                    )


@runtime_checkable
class Tiebreaker(Protocol):
    """A tiebreaker produces a comparable score per participant (higher is better)."""

    name: str

    def score(self, participant_id: Any, ctx: StandingsContext) -> float: ...

    def to_spec(self) -> dict[str, Any]: ...
