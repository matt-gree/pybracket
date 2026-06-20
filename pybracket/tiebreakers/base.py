from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models.enums import AdvancementType, MatchStatus
from ..models.match import Match

__all__ = ["StandingsContext", "Tiebreaker"]

_REAL = frozenset(
    {AdvancementType.RESULT, AdvancementType.FORFEIT, AdvancementType.WALKOVER}
)


class StandingsContext:
    """Precomputed win/loss/opponent data plus stat accumulation for a group of participants.

    Built-in derived inputs (``wins``/``losses`` at match level, ``games_won``/``games_lost``
    from the per-game logs) and caller stat inputs (``stat_for``/``stat_against``/``count``)
    are accumulated from each participant's completed matches and games. ``stat_for``/
    ``stat_against`` are keyed by participant id then stat name; ``count`` is the number of
    games (or, for match-level results, matches) a participant played — the denominator for
    per-game averages. Everything is re-derived from the matches, so edits self-correct.
    """

    def __init__(self, matches: list[Match], participant_ids: list[Any]) -> None:
        self.participant_ids = list(participant_ids)
        self.wins: dict[Any, int] = dict.fromkeys(participant_ids, 0)
        self.losses: dict[Any, int] = dict.fromkeys(participant_ids, 0)
        self.opponents: dict[Any, list[Any]] = {pid: [] for pid in participant_ids}
        self.head_to_head: dict[Any, dict[Any, int]] = {pid: {} for pid in participant_ids}
        self.adv_counts: dict[Any, dict[AdvancementType, int]] = {
            pid: {} for pid in participant_ids
        }
        self.games_won: dict[Any, int] = dict.fromkeys(participant_ids, 0)
        self.games_lost: dict[Any, int] = dict.fromkeys(participant_ids, 0)
        self.count: dict[Any, int] = dict.fromkeys(participant_ids, 0)
        self.stat_for: dict[Any, dict[str, float]] = {pid: {} for pid in participant_ids}
        self.stat_against: dict[Any, dict[str, float]] = {pid: {} for pid in participant_ids}
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
            self._accumulate(m, known)

    def _accumulate(self, m: Match, known: set[Any]) -> None:
        """Sum game records and stat contributions for a completed match (in place)."""
        p1, p2 = m.participant1_id, m.participant2_id
        present = [pid for pid in (p1, p2) if pid in known]
        if m.games:
            for g in m.games:
                if g.winner_id is not None and g.winner_id in known:
                    self.games_won[g.winner_id] += 1
                if g.loser_id is not None and g.loser_id in known:
                    self.games_lost[g.loser_id] += 1
                for pid in present:
                    self.count[pid] += 1
                self._add_stats(g.stats, p1, p2, known)
        else:
            # A match reported match-level (report_result): one unit, stats on Match.stats.
            for pid in present:
                self.count[pid] += 1
            self._add_stats(m.stats, p1, p2, known)

    def _add_stats(
        self, stats: dict[str, dict[Any, float]], p1: Any, p2: Any, known: set[Any]
    ) -> None:
        """Fold a per-id stat dict into stat_for/stat_against for the two participants."""
        for name, vals in stats.items():
            v1 = float(vals.get(p1, 0.0))
            v2 = float(vals.get(p2, 0.0))
            if p1 in known:
                self.stat_for[p1][name] = self.stat_for[p1].get(name, 0.0) + v1
                self.stat_against[p1][name] = self.stat_against[p1].get(name, 0.0) + v2
            if p2 in known:
                self.stat_for[p2][name] = self.stat_for[p2].get(name, 0.0) + v2
                self.stat_against[p2][name] = self.stat_against[p2].get(name, 0.0) + v1


@runtime_checkable
class Tiebreaker(Protocol):
    """A tiebreaker produces a comparable score per participant (higher is better)."""

    name: str

    def score(self, participant_id: Any, ctx: StandingsContext) -> float: ...

    def to_spec(self) -> dict[str, Any]: ...
