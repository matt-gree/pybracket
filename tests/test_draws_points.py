from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import AccumulatedTiebreaker, PointsSystem
from pybracket.tiebreakers import StandingsContext

from tests.helpers import make_participants


def _find(bracket: pb.Bracket, a: int, c: int) -> int:
    return next(
        m.id
        for m in pb.get_ready_matches(bracket)
        if {m.participant1_id, m.participant2_id} == {a, c}
    )


def _points_rr(win: int = 3, draw: int = 1, loss: int = 0) -> pb.Bracket:
    b = pb.generate_round_robin(make_participants(3))
    b.config["points_system"] = PointsSystem(win=win, draw=draw, loss=loss, draws_allowed=True)
    return b


# --------------------------------------------------------------------------------------
# §4a: report_draw, points, ranking
# --------------------------------------------------------------------------------------


def test_report_draw_records_a_draw_for_both() -> None:
    b = _points_rr()
    mid = _find(b, 1, 2)
    b = pb.report_draw(b, mid)
    s = {x.participant_id: x for x in pb.get_standings(b)}
    assert s[1].draws == 1 and s[2].draws == 1
    assert s[1].wins == 0 and s[1].losses == 0
    assert pb.get_match(b, mid).advancement_type is pb.AdvancementType.DRAW


def test_points_drive_ranking() -> None:
    b = _points_rr()  # 3/1/0
    b = pb.report_result(b, _find(b, 1, 2), 1)  # P1 beats P2
    b = pb.report_draw(b, _find(b, 2, 3))  # P2 draws P3
    b = pb.report_result(b, _find(b, 3, 1), 3)  # P3 beats P1
    # points: P1=3, P2=1, P3=4
    standings = {s.participant_id: s for s in pb.get_standings(b)}
    assert standings[3].points == 4.0
    assert standings[1].points == 3.0
    assert standings[2].points == 1.0
    assert [s.participant_id for s in pb.get_standings(b)] == [3, 1, 2]


def test_points_primary_then_win_count() -> None:
    # win=1, draw=1: P1 (2 draws) and P2 (1 win, 1 draw) tie on 2 points; wins break it.
    b = _points_rr(win=1, draw=1, loss=0)
    b = pb.report_draw(b, _find(b, 1, 2))
    b = pb.report_draw(b, _find(b, 1, 3))
    b = pb.report_result(b, _find(b, 2, 3), 2)
    # points: P1=2 (0W), P2=2 (1W), P3=1
    assert [s.participant_id for s in pb.get_standings(b)] == [2, 1, 3]


def test_draw_rejected_for_elimination() -> None:
    b = pb.generate_single_elim(make_participants(4))
    with pytest.raises(pb.InvalidResultError):
        pb.report_draw(b, pb.get_ready_matches(b)[0].id)


def test_draw_rejected_without_points_or_flag() -> None:
    b = pb.generate_round_robin(make_participants(2))  # no points_system, no draws_allowed
    with pytest.raises(pb.InvalidResultError):
        pb.report_draw(b, pb.get_ready_matches(b)[0].id)


def test_draws_allowed_via_config_flag_without_points() -> None:
    b = pb.generate_round_robin(make_participants(2))
    b.config["draws_allowed"] = True  # draws but no points system
    b = pb.report_draw(b, pb.get_ready_matches(b)[0].id)
    s = pb.get_standings(b)
    assert all(x.draws == 1 for x in s)
    assert all(x.points == 0.0 for x in s)  # no points system -> points stay 0


def test_unwind_a_draw() -> None:
    b = _points_rr()
    mid = _find(b, 1, 2)
    b = pb.report_draw(b, mid)
    b, signals = pb.unwind_result(b, mid)
    assert [s.match_id for s in signals] == [mid]
    m = pb.get_match(b, mid)
    assert m.advancement_type is None
    assert m.status is pb.MatchStatus.READY
    assert all(s.draws == 0 for s in pb.get_standings(b))


def test_report_draw_accumulates_stats() -> None:
    b = _points_rr()
    mid = _find(b, 1, 2)
    b = pb.report_draw(b, mid, stats={"runs": (4, 4)})
    ctx = StandingsContext(b.matches, [1, 2, 3], points_system=b.config["points_system"])
    assert ctx.stat_for[1]["runs"] == 4.0
    assert ctx.count[1] == 1


def test_points_and_draws_accumulated_inputs() -> None:
    b = _points_rr()
    b = pb.report_draw(b, _find(b, 1, 2))
    ctx = StandingsContext(b.matches, [1, 2, 3], points_system=b.config["points_system"])
    assert AccumulatedTiebreaker("draws", "for").score(1, ctx) == 1.0
    assert AccumulatedTiebreaker("points", "for").score(1, ctx) == 1.0


def test_points_system_serialization_roundtrip() -> None:
    b = _points_rr()
    b = pb.report_draw(b, _find(b, 1, 2))
    rb = pb.bracket_from_json(pb.bracket_to_json(b))
    assert rb.config["points_system"] == PointsSystem(win=3, draw=1, loss=0, draws_allowed=True)
    # standings re-derive identically after a round-trip
    assert [s.participant_id for s in pb.get_standings(rb)] == [
        s.participant_id for s in pb.get_standings(b)
    ]
    # the drawn match survives
    assert any(m.advancement_type is pb.AdvancementType.DRAW for m in rb.matches)


# --------------------------------------------------------------------------------------
# §4b: even best-of series draws
# --------------------------------------------------------------------------------------


def test_even_best_of_level_series_draws() -> None:
    b = _points_rr()
    b = pb.set_best_of(b, 2)
    mid = _find(b, 1, 2)
    b = pb.report_game(b, mid, 1)
    b = pb.report_game(b, mid, 2)  # 1-1 over best_of=2 -> draw
    m = pb.get_match(b, mid)
    assert m.advancement_type is pb.AdvancementType.DRAW
    assert m.series_score == (1, 1)


def test_even_best_of_sweep_still_wins() -> None:
    b = _points_rr()
    b = pb.set_best_of(b, 2)
    mid = _find(b, 1, 2)
    b = pb.report_game(b, mid, 1)
    b = pb.report_game(b, mid, 1)  # 2-0
    assert pb.get_match(b, mid).winner_id == 1


def test_set_even_best_of_requires_draws() -> None:
    b = pb.generate_round_robin(make_participants(4))  # no draws enabled
    with pytest.raises(pb.ValidationError):
        pb.set_best_of(b, 2)


def test_set_even_best_of_allowed_with_draws() -> None:
    b = _points_rr()
    b = pb.set_best_of(b, 4)
    assert all(m.best_of == 4 for m in b.matches)


def test_report_game_level_series_without_draws_errors() -> None:
    # An even best_of forced onto a non-draw bracket: a level series must not silently draw.
    b = pb.generate_round_robin(make_participants(2))
    for m in b.matches:
        m.best_of = 2
    mid = pb.get_ready_matches(b)[0].id
    p1, p2 = (lambda mm: (mm.participant1_id, mm.participant2_id))(pb.get_match(b, mid))
    b = pb.report_game(b, mid, p1)
    with pytest.raises(pb.InvalidResultError):
        pb.report_game(b, mid, p2)  # 1-1 level, draws not enabled


# --------------------------------------------------------------------------------------
# §4c: Swiss pairs by points
# --------------------------------------------------------------------------------------


def test_swiss_pairs_by_points_with_draws() -> None:
    sw = pb.generate_swiss(make_participants(8), rounds=3)
    sw.config["points_system"] = PointsSystem(win=3, draw=1, loss=0, draws_allowed=True)
    round1 = pb.get_ready_matches(sw)
    for mt in round1:
        a, c = mt.participant1_id, mt.participant2_id
        sw = pb.report_draw(sw, mt.id) if a % 2 == 0 else pb.report_result(sw, mt.id, min(a, c))
    sw = pb.advance_swiss_round(sw)
    round2 = pb.get_ready_matches(sw)
    assert len(round2) == 4
    # No rematches: round-2 pairings are disjoint from round-1 pairings.
    played = {frozenset((m.participant1_id, m.participant2_id)) for m in round1}
    assert all(
        frozenset((m.participant1_id, m.participant2_id)) not in played for m in round2
    )
