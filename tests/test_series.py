from __future__ import annotations

import pybracket as pb
import pytest

from tests.helpers import make_participants


def _ready_match(bracket: pb.Bracket) -> pb.Match:
    return pb.get_ready_matches(bracket)[0]


# --------------------------------------------------------------------------------------
# Clinching
# --------------------------------------------------------------------------------------


def test_bo1_report_game_clinches_immediately() -> None:
    b = pb.generate_single_elim(make_participants(4))
    m = _ready_match(b)
    b = pb.report_game(b, m.id, m.participant1_id)
    mm = pb.get_match(b, m.id)
    assert mm.status is pb.MatchStatus.COMPLETED
    assert mm.winner_id == m.participant1_id
    assert mm.series_score == (1, 0)


def test_bo3_sweep_clinches_at_two() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1 = m.participant1_id
    b = pb.report_game(b, m.id, p1)
    assert pb.get_match(b, m.id).status is pb.MatchStatus.READY  # 1-0, not yet decided
    b = pb.report_game(b, m.id, p1)
    mm = pb.get_match(b, m.id)
    assert mm.status is pb.MatchStatus.COMPLETED
    assert mm.series_score == (2, 0)
    assert len(mm.games) == 2  # series stops at the clinch; no dead third game


def test_bo3_full_series() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1)
    b = pb.report_game(b, m.id, p2)
    assert pb.get_match(b, m.id).series_score == (1, 1)
    assert pb.get_match(b, m.id).status is pb.MatchStatus.READY
    b = pb.report_game(b, m.id, p1)
    mm = pb.get_match(b, m.id)
    assert mm.series_score == (2, 1)
    assert mm.winner_id == p1
    assert mm.loser_id == p2


@pytest.mark.parametrize("best_of", [1, 3, 5, 7])
def test_clinch_count_matches_best_of(best_of: int) -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), best_of)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    clinch = best_of // 2 + 1
    # Take the loser to clinch-1 wins first, interleaved, so the series runs long.
    for _ in range(clinch - 1):
        b = pb.report_game(b, m.id, p2)
    assert pb.get_match(b, m.id).status is pb.MatchStatus.READY
    for _ in range(clinch - 1):
        b = pb.report_game(b, m.id, p1)
    assert pb.get_match(b, m.id).status is pb.MatchStatus.READY  # both at clinch-1
    b = pb.report_game(b, m.id, p1)  # decisive game
    mm = pb.get_match(b, m.id)
    assert mm.status is pb.MatchStatus.COMPLETED
    assert mm.winner_id == p1
    assert max(mm.series_score) == clinch


# --------------------------------------------------------------------------------------
# Advancement parity with report_result
# --------------------------------------------------------------------------------------


def test_report_game_advances_winner_like_report_result() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1 = m.participant1_id
    b = pb.report_game(b, m.id, p1)
    b = pb.report_game(b, m.id, p1)
    nxt = pb.get_match(b, pb.get_match(b, m.id).next_winner_match_id)
    assert p1 in (nxt.participant1_id, nxt.participant2_id)


def test_series_loser_drops_in_double_elim() -> None:
    b = pb.set_best_of(pb.generate_double_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1)
    b = pb.report_game(b, m.id, p1)
    mm = pb.get_match(b, m.id)
    drop = pb.get_match(b, mm.next_loser_match_id)
    assert p2 in (drop.participant1_id, drop.participant2_id)


# --------------------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------------------


def test_stat_tuple_sugar_is_participant_ordered() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1, stats={"runs": (7, 3)})
    g = pb.get_match(b, m.id).games[0]
    assert g.stats == {"runs": {p1: 7.0, p2: 3.0}}


def test_stat_explicit_dict_form() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1, stats={"runs": {p2: 3, p1: 7}})
    g = pb.get_match(b, m.id).games[0]
    assert g.stats == {"runs": {p1: 7.0, p2: 3.0}}


def test_report_result_stores_match_level_stats() -> None:
    b = pb.generate_single_elim(make_participants(4))
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_result(b, m.id, p1, stats={"runs": (5, 2)})
    mm = pb.get_match(b, m.id)
    assert mm.stats == {"runs": {p1: 5.0, p2: 2.0}}
    assert not mm.games


def test_game_metadata_is_preserved() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    b = pb.report_game(b, m.id, m.participant1_id, metadata={"external_id": "g-99"})
    assert pb.get_match(b, m.id).games[0].metadata == {"external_id": "g-99"}


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_report_result_rejected_when_game_log_exists() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    b = pb.report_game(b, m.id, m.participant1_id)
    with pytest.raises(pb.InvalidResultError):
        pb.report_result(b, m.id, m.participant1_id)


def test_report_game_on_completed_series_raises() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1 = m.participant1_id
    b = pb.report_game(b, m.id, p1)
    b = pb.report_game(b, m.id, p1)  # clinched
    with pytest.raises(pb.BracketStateError):
        pb.report_game(b, m.id, p1)


def test_report_game_rejects_non_participant() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    with pytest.raises(pb.InvalidResultError):
        pb.report_game(b, m.id, 999)


def test_report_game_requires_ready_match() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    pending = next(m for m in b.matches if m.status is pb.MatchStatus.PENDING)
    with pytest.raises(pb.BracketStateError):
        pb.report_game(b, pending.id, b.participants[0].id)


def test_report_game_rejected_in_draft() -> None:
    b = pb.generate_swiss(make_participants(8), state=pb.BracketState.DRAFT)
    m = b.matches[0]
    with pytest.raises(pb.BracketStateError):
        pb.report_game(b, m.id, m.participant1_id)


# --------------------------------------------------------------------------------------
# Unwind
# --------------------------------------------------------------------------------------


def test_unwind_game_mid_series_drops_last_game() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1)
    b = pb.report_game(b, m.id, p2)
    b, signals = pb.unwind_game(b, m.id)
    mm = pb.get_match(b, m.id)
    assert signals == []
    assert mm.series_score == (1, 0)
    assert mm.status is pb.MatchStatus.READY
    assert len(mm.games) == 1


def test_unwind_game_unclinches_and_cascades() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1)
    b = pb.report_game(b, m.id, p2)
    b = pb.report_game(b, m.id, p1)  # clinch 2-1
    next_id = pb.get_match(b, m.id).next_winner_match_id

    b, signals = pb.unwind_game(b, m.id)
    mm = pb.get_match(b, m.id)
    assert [s.match_id for s in signals] == [m.id]
    assert mm.status is pb.MatchStatus.READY
    assert mm.winner_id is None
    assert mm.series_score == (1, 1)  # earlier games intact
    assert len(mm.games) == 2
    # The advancement was reversed downstream.
    nxt = pb.get_match(b, next_id)
    assert p1 not in (nxt.participant1_id, nxt.participant2_id)


def test_unwind_game_no_games_raises() -> None:
    b = pb.generate_single_elim(make_participants(4))
    m = _ready_match(b)
    with pytest.raises(pb.BracketStateError):
        pb.unwind_game(b, m.id)


def test_unwind_result_clears_whole_series() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1, stats={"runs": (7, 3)})
    b = pb.report_game(b, m.id, p2)
    b = pb.report_game(b, m.id, p1)
    next_id = pb.get_match(b, m.id).next_winner_match_id

    b, signals = pb.unwind_result(b, m.id)
    mm = pb.get_match(b, m.id)
    assert [s.match_id for s in signals] == [m.id]
    assert mm.games == []
    assert mm.stats == {}
    assert mm.status is pb.MatchStatus.READY
    assert mm.winner_id is None
    nxt = pb.get_match(b, next_id)
    assert p1 not in (nxt.participant1_id, nxt.participant2_id)


# --------------------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------------------


def test_dict_roundtrip_preserves_series_and_stats() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1, p2 = m.participant1_id, m.participant2_id
    b = pb.report_game(b, m.id, p1, stats={"runs": (7, 3)}, metadata={"g": 1})
    b = pb.report_game(b, m.id, p2, stats={"runs": (2, 5)})

    rb = pb.bracket_from_dict(pb.bracket_to_dict(b))
    rmm = pb.get_match(rb, m.id)
    assert rmm.series_score == (1, 1)
    assert rmm.games[0].stats == {"runs": {p1: 7.0, p2: 3.0}}
    assert rmm.games[0].metadata == {"g": 1}
    assert rmm.games[1].winner_id == p2


def test_json_roundtrip_preserves_series() -> None:
    b = pb.set_best_of(pb.generate_single_elim(make_participants(4)), 3)
    m = _ready_match(b)
    p1 = m.participant1_id
    b = pb.report_game(b, m.id, p1)
    b = pb.report_game(b, m.id, p1)  # clinch

    rb = pb.bracket_from_json(pb.bracket_to_json(b))
    rmm = pb.get_match(rb, m.id)
    assert rmm.series_score == (2, 0)
    assert rmm.winner_id == p1
    assert rmm.status is pb.MatchStatus.COMPLETED
