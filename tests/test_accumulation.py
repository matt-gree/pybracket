from __future__ import annotations

import pybracket as pb
import pytest
from pybracket.tiebreakers import StandingsContext

from tests.helpers import make_participants


def _ctx(bracket: pb.Bracket) -> StandingsContext:
    return StandingsContext(bracket.matches, [p.id for p in bracket.participants])


def _play_series(bracket: pb.Bracket, match_id: int, games: list) -> pb.Bracket:
    """games: list of (winner_id, stats) tuples reported in order."""
    for winner, stats in games:
        bracket = pb.report_game(bracket, match_id, winner, stats=stats)
    return bracket


# --------------------------------------------------------------------------------------
# Built-in game records
# --------------------------------------------------------------------------------------


def test_games_won_and_lost_from_logs() -> None:
    b = pb.set_best_of(pb.generate_round_robin(make_participants(2)), 3)
    m = pb.get_ready_matches(b)[0]
    p1, p2 = m.participant1_id, m.participant2_id
    b = _play_series(b, m.id, [(p1, None), (p2, None), (p1, None)])  # 2-1
    ctx = _ctx(b)
    assert ctx.games_won[p1] == 2
    assert ctx.games_lost[p1] == 1
    assert ctx.games_won[p2] == 1
    assert ctx.games_lost[p2] == 2
    assert ctx.count[p1] == 3 == ctx.count[p2]


def test_match_level_result_has_no_game_record() -> None:
    # A report_result match counts as a played match (count=1) but contributes no games_won.
    b = pb.generate_round_robin(make_participants(2))
    m = pb.get_ready_matches(b)[0]
    p1 = m.participant1_id
    b = pb.report_result(b, m.id, p1)
    ctx = _ctx(b)
    assert ctx.wins[p1] == 1
    assert ctx.games_won[p1] == 0  # strictly from game logs (documented)
    assert ctx.count[p1] == 1


def test_in_progress_series_does_not_accumulate() -> None:
    b = pb.set_best_of(pb.generate_round_robin(make_participants(2)), 3)
    m = pb.get_ready_matches(b)[0]
    p1 = m.participant1_id
    b = pb.report_game(b, m.id, p1)  # 1-0, series not decided
    ctx = _ctx(b)
    assert ctx.games_won[p1] == 0  # match not COMPLETED -> excluded from standings
    assert ctx.count[p1] == 0


def test_bye_does_not_count_toward_games_or_stats() -> None:
    b = pb.generate_single_elim(make_participants(3))  # seed 1 gets a first-round bye
    ctx = _ctx(b)
    # Whoever has the bye: games/count untouched, only the BYE adv counter bumped.
    assert all(ctx.count[pid] == 0 for pid in [1, 2, 3])
    assert all(ctx.games_won[pid] == 0 for pid in [1, 2, 3])


# --------------------------------------------------------------------------------------
# Caller stat accumulation
# --------------------------------------------------------------------------------------


def test_stat_for_against_and_diff() -> None:
    b = pb.set_best_of(pb.generate_round_robin(make_participants(2)), 3)
    m = pb.get_ready_matches(b)[0]
    p1, p2 = m.participant1_id, m.participant2_id
    b = _play_series(
        b,
        m.id,
        [(p1, {"runs": {p1: 5, p2: 2}}), (p1, {"runs": {p1: 4, p2: 1}})],
    )
    ctx = _ctx(b)
    assert ctx.stat_for[p1]["runs"] == 9.0
    assert ctx.stat_against[p1]["runs"] == 3.0
    assert ctx.stat_for[p2]["runs"] == 3.0
    assert ctx.stat_against[p2]["runs"] == 9.0


def test_tuple_sugar_accumulates() -> None:
    b = pb.set_best_of(pb.generate_round_robin(make_participants(2)), 3)
    m = pb.get_ready_matches(b)[0]
    p1 = m.participant1_id
    b = _play_series(b, m.id, [(p1, {"runs": (5, 2)}), (p1, {"runs": (4, 1)})])
    ctx = _ctx(b)
    assert ctx.stat_for[p1]["runs"] == 9.0
    assert ctx.stat_against[p1]["runs"] == 3.0


def test_match_level_stats_accumulate() -> None:
    b = pb.generate_round_robin(make_participants(2))
    m = pb.get_ready_matches(b)[0]
    p1 = m.participant1_id
    b = pb.report_result(b, m.id, p1, stats={"runs": (7, 3)})
    ctx = _ctx(b)
    assert ctx.stat_for[p1]["runs"] == 7.0
    assert ctx.stat_against[p1]["runs"] == 3.0
    assert ctx.count[p1] == 1  # one match unit -> avg denominator


def test_count_is_average_denominator() -> None:
    # Round robin of 3, every match a 2-0 sweep with the lower seed scoring 5 then 4.
    b = pb.set_best_of(pb.generate_round_robin(make_participants(3)), 3)
    while not pb.is_complete(b):
        for m in pb.get_ready_matches(b):
            w, loser = sorted((m.participant1_id, m.participant2_id))
            b = _play_series(
                b, m.id, [(w, {"runs": {w: 5, loser: 2}}), (w, {"runs": {w: 4, loser: 1}})]
            )
    ctx = _ctx(b)
    # P1 swept both opponents: 4 games, 18 runs -> 4.5 runs/game.
    assert ctx.count[1] == 4
    assert ctx.stat_for[1]["runs"] / ctx.count[1] == pytest.approx(4.5)


# --------------------------------------------------------------------------------------
# Serialization survives accumulation (typed-id coercion)
# --------------------------------------------------------------------------------------


def test_json_roundtrip_preserves_stat_accumulation() -> None:
    b = pb.set_best_of(pb.generate_round_robin(make_participants(2)), 3)
    m = pb.get_ready_matches(b)[0]
    p1 = m.participant1_id
    b = _play_series(b, m.id, [(p1, {"runs": (5, 2)}), (p1, {"runs": (4, 1)})])

    rb = pb.bracket_from_json(pb.bracket_to_json(b))
    ctx = _ctx(rb)
    # int participant ids look up correctly despite JSON having stringified the stat keys
    assert ctx.stat_for[p1]["runs"] == 9.0
    assert ctx.stat_against[p1]["runs"] == 3.0
    assert ctx.games_won[p1] == 2


def test_dict_roundtrip_preserves_typed_stat_keys() -> None:
    b = pb.set_best_of(pb.generate_round_robin(make_participants(2)), 3)
    m = pb.get_ready_matches(b)[0]
    p1 = m.participant1_id
    b = pb.report_game(b, m.id, p1, stats={"runs": (5, 2)})

    rb = pb.bracket_from_dict(pb.bracket_to_dict(b))
    g = pb.get_match(rb, m.id).games[0]
    assert g.stats["runs"][p1] == 5.0  # key is still the int id, not "1"
