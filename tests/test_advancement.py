from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import AdvancementType, MatchStatus

from tests.helpers import make_participants


def test_report_result_advances_winner() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    semi = pb.get_ready_matches(bracket)[0]
    new = pb.report_result(bracket, semi.id, semi.participant1_id)
    # Original bracket is unchanged (immutable-ish API).
    assert pb.get_match(bracket, semi.id).status is MatchStatus.READY
    assert pb.get_match(new, semi.id).status is MatchStatus.COMPLETED
    final = [m for m in new.matches if m.round_number == 2][0]
    assert semi.participant1_id in (final.participant1_id, final.participant2_id)


def test_report_result_sets_loser_and_winner() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    m = pb.get_ready_matches(bracket)[0]
    new = pb.report_result(bracket, m.id, m.participant1_id)
    updated = pb.get_match(new, m.id)
    assert updated.winner_id == m.participant1_id
    assert updated.loser_id == m.participant2_id
    assert updated.advancement_type is AdvancementType.RESULT


def test_invalid_winner_raises() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    m = pb.get_ready_matches(bracket)[0]
    with pytest.raises(pb.InvalidResultError):
        pb.report_result(bracket, m.id, 999)


def test_unknown_match_raises() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    with pytest.raises(pb.MatchNotFoundError):
        pb.report_result(bracket, 9999, 1)


def test_double_report_raises() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id)
    with pytest.raises(pb.BracketStateError):
        pb.report_result(bracket, m.id, m.participant2_id)


def test_forfeit_and_walkover_count_as_wins() -> None:
    bracket = pb.generate_round_robin(make_participants(4))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id, AdvancementType.FORFEIT)
    standings = {s.participant_id: s for s in pb.get_standings(bracket)}
    assert standings[m.participant1_id].wins == 1
    assert standings[m.participant1_id].advancement_type_counts.get(AdvancementType.FORFEIT) == 1


def test_metadata_attached_and_preserved() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id, metadata={"game_id": "abc"})
    assert pb.get_match(bracket, m.id).metadata["game_id"] == "abc"


def test_invalid_advancement_type_raises() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    m = pb.get_ready_matches(bracket)[0]
    with pytest.raises(pb.InvalidResultError):
        pb.report_result(bracket, m.id, m.participant1_id, AdvancementType.BYE)


def test_bye_counts_tracked_separately() -> None:
    bracket = pb.generate_single_elim(make_participants(3))
    bye_match = [m for m in bracket.matches if m.status is MatchStatus.BYE][0]
    assert bye_match.advancement_type is AdvancementType.BYE
    assert bye_match.winner_id == 1  # top seed received the bye
