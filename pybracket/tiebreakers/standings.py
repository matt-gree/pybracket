from __future__ import annotations

from typing import Any

from ..models.bracket import Bracket
from ..models.match import Match
from ..models.points import PointsSystem
from ..models.standing import Standing
from .accumulated import AccumulatedTiebreaker
from .base import RelationalTiebreaker, StandingsContext, Tiebreaker
from .buchholz import BuchholzTiebreaker
from .head_to_head import HeadToHeadTiebreaker
from .mini_league import MiniLeagueTiebreaker
from .stat_tiebreaker import StatTiebreaker
from .win_count import WinCountTiebreaker

__all__ = [
    "get_standings",
    "default_tiebreakers",
    "serialize_tiebreakers",
    "deserialize_tiebreakers",
]


def default_tiebreakers() -> list[Tiebreaker]:
    return [WinCountTiebreaker(), HeadToHeadTiebreaker()]


def serialize_tiebreakers(tiebreakers: list[Tiebreaker]) -> list[dict[str, Any]]:
    return [tb.to_spec() for tb in tiebreakers]


def deserialize_tiebreakers(
    specs: list[dict[str, Any]] | None,
    participants: list[Any] | None = None,
) -> list[Tiebreaker]:
    if not specs:
        return default_tiebreakers()
    chain: list[Tiebreaker] = []
    for spec in specs:
        kind = spec.get("type")
        if kind == "win_count":
            chain.append(WinCountTiebreaker())
        elif kind == "head_to_head":
            chain.append(HeadToHeadTiebreaker())
        elif kind == "buchholz":
            chain.append(BuchholzTiebreaker(truncated=bool(spec.get("truncated", False))))
        elif kind == "accumulated":
            chain.append(
                AccumulatedTiebreaker(
                    input=spec["input"],
                    agg=spec.get("agg", "diff"),
                    higher_is_better=bool(spec.get("higher_is_better", True)),
                )
            )
        elif kind == "mini_league":
            chain.append(MiniLeagueTiebreaker())
        elif kind == "stat":
            tb = StatTiebreaker(
                stat_key=spec["stat_key"],
                higher_is_better=bool(spec.get("higher_is_better", True)),
                default=float(spec.get("default", 0.0)),
            )
            if participants is not None:
                tb.bind(participants)
            chain.append(tb)
    return chain or default_tiebreakers()


def _points_system(bracket: Bracket) -> PointsSystem | None:
    ps = bracket.config.get("points_system")
    if isinstance(ps, PointsSystem):
        return ps
    if isinstance(ps, dict):
        return PointsSystem.from_spec(ps)
    return None


def _build_chain(bracket: Bracket) -> list[Tiebreaker]:
    specs = bracket.config.get("tiebreakers")
    chain = deserialize_tiebreakers(specs, bracket.participants)
    # Primary sort: points when a PointsSystem is configured, else match wins (today's behaviour).
    primary: Tiebreaker = (
        AccumulatedTiebreaker("points", "for")
        if _points_system(bracket) is not None
        else WinCountTiebreaker()
    )
    if not any(tb.name == primary.name for tb in chain):
        chain = [primary, *chain]
    return chain


def get_standings(bracket: Bracket) -> list[Standing]:
    """Rank participants by the scalar tiebreaker chain, then relational cohort reorders.

    Scalar tiebreakers (win count, accumulated stats, …) build a sort key and rank the whole
    field. Relational tiebreakers (head-to-head, mini-league) then reorder, in chain order, only
    the cohorts the scalars left tied — their answer depends on which participants are tied, so
    they cannot be a global score. A cohort no tiebreaker can separate shares a rank.
    """
    pids = [p.id for p in bracket.participants]
    ctx = StandingsContext(bracket.matches, pids, points_system=_points_system(bracket))
    chain = _build_chain(bracket)
    scalars = [tb for tb in chain if not isinstance(tb, RelationalTiebreaker)]
    relationals = [tb for tb in chain if isinstance(tb, RelationalTiebreaker)]

    score_map: dict[Any, dict[str, float]] = {
        pid: {tb.name: tb.score(pid, ctx) for tb in scalars} for pid in pids
    }
    score_key: dict[Any, tuple[float, ...]] = {
        pid: tuple(score_map[pid][tb.name] for tb in scalars) for pid in pids
    }
    seed_of = {p.id: p.seed for p in bracket.participants}

    order = sorted(pids, key=lambda pid: (tuple(-s for s in score_key[pid]), seed_of[pid]))
    groups = _scalar_groups(order, score_key)
    for tb in relationals:
        groups = _refine_cohorts(groups, tb, ctx, bracket.matches, seed_of)

    standings: list[Standing] = []
    rank = 1
    for group in groups:
        for pid in group:
            standings.append(
                Standing(
                    participant_id=pid,
                    rank=rank,
                    wins=ctx.wins[pid],
                    losses=ctx.losses[pid],
                    draws=ctx.draws[pid],
                    points=ctx.points[pid],
                    advancement_type_counts=dict(ctx.adv_counts[pid]),
                    tiebreaker_scores=dict(score_map[pid]),
                )
            )
        rank += len(group)
    return standings


def _scalar_groups(
    order: list[Any], score_key: dict[Any, tuple[float, ...]]
) -> list[list[Any]]:
    """Partition the scalar-sorted order into cohorts sharing an identical score key."""
    groups: list[list[Any]] = []
    i, n = 0, len(order)
    while i < n:
        j = i + 1
        while j < n and score_key[order[j]] == score_key[order[i]]:
            j += 1
        groups.append(order[i:j])
        i = j
    return groups


def _refine_cohorts(
    groups: list[list[Any]],
    tb: RelationalTiebreaker,
    ctx: StandingsContext,
    matches: list[Match],
    seed_of: dict[Any, int],
) -> list[list[Any]]:
    """Reorder each still-tied cohort by a relational tiebreaker, splitting where it separates."""
    refined: list[list[Any]] = []
    for group in groups:
        if len(group) == 1:
            refined.append(group)
            continue
        cohort = set(group)
        value = {pid: tb.cohort_value(pid, cohort, ctx, matches) for pid in group}
        ordered = sorted(group, key=lambda pid: (-value[pid], seed_of[pid]))
        i, n = 0, len(ordered)
        while i < n:
            j = i + 1
            while j < n and value[ordered[j]] == value[ordered[i]]:
                j += 1
            refined.append(ordered[i:j])
            i = j
    return refined
