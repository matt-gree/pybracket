from __future__ import annotations

from typing import Any

from pybracket import (
    AdvancementType,
    Bracket,
    BracketSide,
    BracketState,
    Match,
    MatchStatus,
    Participant,
    get_standings,
)


def _match(match_id: int, winner: int, loser: int) -> Match:
    return Match(
        id=match_id,
        round_number=1,
        bracket_side=BracketSide.WINNERS,
        participant1_id=winner,
        participant2_id=loser,
        winner_id=winner,
        loser_id=loser,
        advancement_type=AdvancementType.RESULT,
        next_winner_match_id=None,
        next_loser_match_id=None,
        status=MatchStatus.COMPLETED,
    )


def _standings(
    n: int, results: list[tuple[int, int]], tiebreakers: list[dict[str, Any]]
) -> dict[int, int]:
    matches = [_match(i + 1, w, ll) for i, (w, ll) in enumerate(results)]
    participants = [Participant(id=i, seed=i, name=f"P{i}") for i in range(1, n + 1)]
    bracket = Bracket(
        format="round_robin",
        state=BracketState.COMPLETE,
        participants=participants,
        matches=matches,
        rounds=[],
        config={"tiebreakers": tiebreakers},
    )
    return {s.participant_id: s.rank for s in get_standings(bracket)}


def test_mini_league_orders_transitive_three_way_tie() -> None:
    # P1, P2, P3 all finish 2 wins. Among themselves: P1 beat both, P2 beat P3.
    results = [
        (1, 2),  # P1 > P2
        (1, 3),  # P1 > P3
        (2, 3),  # P2 > P3
        (4, 1),  # outsiders beat P1 ...
        (5, 1),
        (2, 4),  # ... P2 beats an outsider
        (3, 4),  # ... P3 beats outsiders
        (3, 5),
    ]
    ranks = _standings(
        5, results, [{"type": "win_count"}, {"type": "mini_league"}]
    )
    assert ranks[1] < ranks[2] < ranks[3]  # mini-league sub-table P1 > P2 > P3


def test_mini_league_cannot_break_a_cycle() -> None:
    # Rock-paper-scissors among three 2-win teams -> all share a rank.
    results = [
        (1, 2),  # P1 > P2
        (2, 3),  # P2 > P3
        (3, 1),  # P3 > P1  (cycle)
        (1, 4),
        (2, 4),
        (3, 4),
    ]
    ranks = _standings(
        4, results, [{"type": "win_count"}, {"type": "mini_league"}]
    )
    assert ranks[1] == ranks[2] == ranks[3] == 1  # unresolved -> co-ranked


def test_purified_head_to_head_respects_actual_result() -> None:
    # P1 and P2 both finish 2 wins; P1 BEAT P2 head-to-head, but P2 has fewer losses
    # (the case the old hybrid scalar net-h2h term got WRONG by ranking P2 above P1).
    results = [
        (1, 2),  # P1 > P2  (head-to-head)
        (1, 3),  # P1 > P3
        (4, 1),  # P1 loses twice -> 2-2
        (5, 1),
        (2, 3),  # P2 beats two -> 2-1
        (2, 4),
    ]
    ranks = _standings(
        5, results, [{"type": "win_count"}, {"type": "head_to_head"}]
    )
    assert ranks[1] < ranks[2]  # P1 above P2 because P1 beat P2


def test_head_to_head_then_mini_league_runs_in_chain_order() -> None:
    # Two teams separable by head-to-head; relational passes apply in order.
    results = [
        (1, 2),  # P1 > P2 head-to-head
        (1, 3),
        (2, 3),
        (4, 1),
        (4, 2),
    ]
    ranks = _standings(
        4,
        results,
        [{"type": "win_count"}, {"type": "head_to_head"}, {"type": "mini_league"}],
    )
    # P1 and P2 both 2 wins; head-to-head (first relational pass) puts P1 above P2.
    assert ranks[1] < ranks[2]
