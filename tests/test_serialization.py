from __future__ import annotations

import uuid

import pybracket as pb
import pytest

from tests.helpers import make_participants, simulate


def _make(fmt: str) -> pb.Bracket:
    players = make_participants(8)
    if fmt == "single_elim":
        return pb.generate_single_elim(players, third_place_match=True)
    if fmt == "double_elim":
        return pb.generate_double_elim(players)
    if fmt == "round_robin":
        return pb.generate_round_robin(players)
    if fmt == "swiss":
        return pb.generate_swiss(players)
    if fmt == "gauntlet":
        return pb.generate_gauntlet(players, style="single")
    raise AssertionError(fmt)


FORMATS = ["single_elim", "double_elim", "round_robin", "swiss", "gauntlet"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_dict_round_trip(fmt: str) -> None:
    bracket = _make(fmt)
    assert pb.bracket_from_dict(pb.bracket_to_dict(bracket)) == bracket


@pytest.mark.parametrize("fmt", FORMATS)
def test_json_round_trip(fmt: str) -> None:
    bracket = _make(fmt)
    assert pb.bracket_from_json(pb.bracket_to_json(bracket)) == bracket


@pytest.mark.parametrize("fmt", FORMATS)
def test_mid_tournament_round_trip(fmt: str) -> None:
    bracket = _make(fmt)
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id, metadata={"game": 7})
    assert pb.bracket_from_dict(pb.bracket_to_dict(bracket)) == bracket


@pytest.mark.parametrize("fmt", ["single_elim", "double_elim", "round_robin"])
def test_completed_round_trip(fmt: str) -> None:
    bracket = simulate(_make(fmt))
    assert pb.bracket_from_dict(pb.bracket_to_dict(bracket)) == bracket


def test_int_ids_survive_json() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    restored = pb.bracket_from_json(pb.bracket_to_json(bracket))
    assert [p.id for p in restored.participants] == [p.id for p in bracket.participants]


def test_str_ids_survive_dict() -> None:
    players = [pb.Participant(id=f"team-{i}", seed=i, name=f"T{i}") for i in range(1, 9)]
    bracket = pb.generate_single_elim(players)
    restored = pb.bracket_from_dict(pb.bracket_to_dict(bracket))
    assert restored == bracket
    assert all(isinstance(p.id, str) for p in restored.participants)


def test_uuid_ids_survive_dict() -> None:
    players = [pb.Participant(id=uuid.uuid4(), seed=i, name=f"U{i}") for i in range(1, 9)]
    bracket = pb.generate_single_elim(players)
    restored = pb.bracket_from_dict(pb.bracket_to_dict(bracket))
    assert restored == bracket
    assert all(isinstance(p.id, uuid.UUID) for p in restored.participants)


def test_uuid_ids_serialize_to_json() -> None:
    # UUID ids are not JSON-native; bracket_to_json stringifies them via _json_default.
    players = [pb.Participant(id=uuid.uuid4(), seed=i, name=f"U{i}") for i in range(1, 5)]
    bracket = pb.generate_single_elim(players)
    text = pb.bracket_to_json(bracket)
    assert str(players[0].id) in text
    restored = pb.bracket_from_json(text)
    # Ids come back as strings (JSON has no UUID type); structure is otherwise preserved.
    assert {str(p.id) for p in players} == {p.id for p in restored.participants}


def test_swiss_pairing_method_round_trips() -> None:
    bracket = pb.generate_swiss(make_participants(8), pairing_method=pb.PairingMethod.DUTCH)
    restored = pb.bracket_from_dict(pb.bracket_to_dict(bracket))
    assert restored.config["pairing_method"] is pb.PairingMethod.DUTCH
    assert restored == bracket
