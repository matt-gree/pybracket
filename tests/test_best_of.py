from __future__ import annotations

import pybracket as pb
import pytest

from tests.helpers import make_participants


def test_default_best_of_is_one() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    assert all(m.best_of == 1 for m in bracket.matches)


def test_set_best_of_global() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    bracket = pb.set_best_of(bracket, 3)
    assert all(m.best_of == 3 for m in bracket.matches)


def test_round_overrides_take_precedence() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    bracket = pb.set_best_of(bracket, 3, round_overrides={2: 5, 3: 7})
    by_round = {m.round_number: m.best_of for m in bracket.matches}
    assert by_round[1] == 3
    assert by_round[2] == 5
    assert by_round[3] == 7
    # Round-level best_of is recorded on the Round too.
    rounds = {r.number: r.best_of for r in bracket.rounds}
    assert rounds[2] == 5
    assert rounds[3] == 7


def test_even_best_of_rejected() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    with pytest.raises(pb.ValidationError):
        pb.set_best_of(bracket, 2)


def test_cannot_change_started_round_global() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id)
    with pytest.raises(pb.BracketStateError):
        pb.set_best_of(bracket, 3)


def test_cannot_change_started_round_override() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id)
    with pytest.raises(pb.BracketStateError):
        pb.set_best_of(bracket, 1, round_overrides={1: 3})


def test_can_set_future_round_after_play() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id)
    # Round 3 has not begun, so overriding only it is allowed.
    bracket = pb.set_best_of(bracket, 1, round_overrides={3: 5})
    by_round = {m.round_number: m.best_of for m in bracket.matches}
    assert by_round[3] == 5
