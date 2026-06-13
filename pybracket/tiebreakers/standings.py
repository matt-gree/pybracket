from __future__ import annotations

from typing import Any

from ..models.bracket import Bracket
from ..models.standing import Standing
from .base import StandingsContext, Tiebreaker
from .buchholz import BuchholzTiebreaker
from .head_to_head import HeadToHeadTiebreaker
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


def _build_chain(bracket: Bracket) -> list[Tiebreaker]:
    specs = bracket.config.get("tiebreakers")
    chain = deserialize_tiebreakers(specs, bracket.participants)
    if not any(tb.name == "win_count" for tb in chain):
        chain = [WinCountTiebreaker(), *chain]
    return chain


def _reorder_head_to_head(
    order: list[Any],
    score_key: dict[Any, tuple[float, ...]],
    ctx: StandingsContext,
) -> list[Any]:
    result: list[Any] = []
    i = 0
    n = len(order)
    while i < n:
        j = i + 1
        while j < n and score_key[order[j]] == score_key[order[i]]:
            j += 1
        cohort = order[i:j]
        if len(cohort) > 1:
            cohort_set = set(cohort)
            cohort.sort(
                key=lambda pid: -sum(
                    v for opp, v in ctx.head_to_head.get(pid, {}).items() if opp in cohort_set
                )
            )
        result.extend(cohort)
        i = j
    return result


def get_standings(bracket: Bracket) -> list[Standing]:
    """Rank participants by wins, then by the configured tiebreaker chain."""
    pids = [p.id for p in bracket.participants]
    ctx = StandingsContext(bracket.matches, pids)
    chain = _build_chain(bracket)

    score_map: dict[Any, dict[str, float]] = {
        pid: {tb.name: tb.score(pid, ctx) for tb in chain} for pid in pids
    }
    score_key: dict[Any, tuple[float, ...]] = {
        pid: tuple(score_map[pid][tb.name] for tb in chain) for pid in pids
    }
    seed_of = {p.id: p.seed for p in bracket.participants}

    order = sorted(pids, key=lambda pid: (tuple(-s for s in score_key[pid]), seed_of[pid]))
    if any(tb.name == "head_to_head" for tb in chain):
        order = _reorder_head_to_head(order, score_key, ctx)

    standings: list[Standing] = []
    rank = 0
    for idx, pid in enumerate(order):
        if idx == 0 or not _same_position(order[idx - 1], pid, score_key, ctx, chain):
            rank = idx + 1
        standings.append(
            Standing(
                participant_id=pid,
                rank=rank,
                wins=ctx.wins[pid],
                losses=ctx.losses[pid],
                advancement_type_counts=dict(ctx.adv_counts[pid]),
                tiebreaker_scores=dict(score_map[pid]),
            )
        )
    return standings


def _same_position(
    a: Any,
    b: Any,
    score_key: dict[Any, tuple[float, ...]],
    ctx: StandingsContext,
    chain: list[Tiebreaker],
) -> bool:
    if score_key[a] != score_key[b]:
        return False
    # Tied on every score but separable head-to-head -> distinct positions.
    has_h2h = any(tb.name == "head_to_head" for tb in chain)
    return not (has_h2h and ctx.head_to_head.get(a, {}).get(b, 0) != 0)
