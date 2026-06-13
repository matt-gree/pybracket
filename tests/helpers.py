from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pybracket as pb
from pybracket import Bracket, Match, Participant


def make_participants(
    n: int, *, stats: dict[int, dict[str, Any]] | None = None
) -> list[Participant]:
    stats = stats or {}
    return [
        Participant(id=i, seed=i, name=f"P{i}", stats=dict(stats.get(i, {})))
        for i in range(1, n + 1)
    ]


def lower_seed_wins(bracket: Bracket, match: Match) -> Any:
    """Decision function: the better (lower) seed always wins."""
    p1 = pb.get_participant(bracket, match.participant1_id)
    p2 = pb.get_participant(bracket, match.participant2_id)
    return min((p1, p2), key=lambda p: p.seed).id


def simulate(
    bracket: Bracket,
    decide: Callable[[Bracket, Match], Any] = lower_seed_wins,
    *,
    advance_swiss: bool = False,
    max_steps: int = 1000,
) -> Bracket:
    """Play a bracket to completion using `decide` to pick winners."""
    steps = 0
    while not pb.is_complete(bracket):
        steps += 1
        assert steps < max_steps, "simulation did not terminate"
        ready = pb.get_ready_matches(bracket)
        if not ready:
            if advance_swiss and bracket.format == "swiss":
                bracket = pb.advance_swiss_round(bracket)
                continue
            raise AssertionError("no ready matches but bracket is not complete")
        for match in ready:
            winner = decide(bracket, match)
            bracket = pb.report_result(bracket, match.id, winner)
    return bracket
