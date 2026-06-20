from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import AccumulatedTiebreaker
from pybracket.tiebreakers import StandingsContext, deserialize_tiebreakers

from tests.helpers import make_participants


def _series_ctx() -> tuple[StandingsContext, int, int]:
    """A 2-player BO3: p1 wins 2-1; runs p1 {5,1,6} vs p2 {2,4,3}."""
    b = pb.set_best_of(pb.generate_round_robin(make_participants(2)), 3)
    m = pb.get_ready_matches(b)[0]
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1, stats={"runs": {p1: 5, p2: 2}})
    b = pb.report_game(b, m.id, p2, stats={"runs": {p1: 1, p2: 4}})
    b = pb.report_game(b, m.id, p1, stats={"runs": {p1: 6, p2: 3}})
    return StandingsContext(b.matches, [p1, p2]), p1, p2


def test_wins_for_equals_win_count() -> None:
    ctx, p1, p2 = _series_ctx()
    tb = AccumulatedTiebreaker("wins", "for")
    assert tb.score(p1, ctx) == 1.0  # series winner
    assert tb.score(p2, ctx) == 0.0


def test_games_aggregations() -> None:
    ctx, p1, p2 = _series_ctx()
    assert AccumulatedTiebreaker("games", "for").score(p1, ctx) == 2.0
    assert AccumulatedTiebreaker("games", "against").score(p1, ctx) == 1.0
    assert AccumulatedTiebreaker("games", "diff").score(p1, ctx) == 1.0
    assert AccumulatedTiebreaker("games", "diff").score(p2, ctx) == -1.0


def test_caller_stat_aggregations() -> None:
    ctx, p1, p2 = _series_ctx()
    assert AccumulatedTiebreaker("runs", "for").score(p1, ctx) == 12.0
    assert AccumulatedTiebreaker("runs", "against").score(p1, ctx) == 9.0
    assert AccumulatedTiebreaker("runs", "diff").score(p1, ctx) == 3.0
    assert AccumulatedTiebreaker("runs", "diff").score(p2, ctx) == -3.0


def test_count_and_avg() -> None:
    ctx, p1, _ = _series_ctx()
    assert AccumulatedTiebreaker("runs", "count").score(p1, ctx) == 3.0  # 3 games
    assert AccumulatedTiebreaker("runs", "avg").score(p1, ctx) == 4.0  # 12 / 3


def test_avg_with_no_games_is_zero() -> None:
    ctx = StandingsContext([], [1, 2])
    assert AccumulatedTiebreaker("runs", "avg").score(1, ctx) == 0.0


def test_higher_is_better_flips_direction() -> None:
    ctx, p1, _ = _series_ctx()
    against = AccumulatedTiebreaker("runs", "against", higher_is_better=False)
    assert against.score(p1, ctx) == -9.0  # fewer-against ranks higher


def test_missing_stat_defaults_to_zero() -> None:
    ctx, p1, _ = _series_ctx()
    assert AccumulatedTiebreaker("hits", "for").score(p1, ctx) == 0.0


def test_invalid_agg_raises() -> None:
    with pytest.raises(pb.ValidationError):
        AccumulatedTiebreaker("runs", "median")


def test_spec_roundtrip() -> None:
    original = AccumulatedTiebreaker("runs", "diff", higher_is_better=False)
    (restored,) = deserialize_tiebreakers([original.to_spec()])
    assert isinstance(restored, AccumulatedTiebreaker)
    assert restored.input == "runs"
    assert restored.agg == "diff"
    assert restored.higher_is_better is False


def test_accumulated_breaks_tie_in_standings() -> None:
    # Cyclic 1-win-each, separated by run differential (a scalar tiebreaker).
    b = pb.generate_round_robin(make_participants(3))

    def report(a: int, c: int, winner: int, stats: dict) -> None:
        nonlocal b
        m = next(
            m
            for m in pb.get_ready_matches(b)
            if {m.participant1_id, m.participant2_id} == {a, c}
        )
        b = pb.report_result(b, m.id, winner, stats=stats)

    report(1, 2, 1, {"runs": {1: 10, 2: 0}})
    report(3, 1, 3, {"runs": {3: 1, 1: 0}})
    report(2, 3, 2, {"runs": {2: 1, 3: 0}})
    # run diffs: P1 +9, P3 0, P2 -9
    b.config["tiebreakers"] = [
        {"type": "win_count"},
        {"type": "accumulated", "input": "runs", "agg": "diff"},
    ]
    order = [s.participant_id for s in pb.get_standings(b)]
    assert order == [1, 3, 2]
