from __future__ import annotations

import pybracket as pb
import pytest

from tests.helpers import make_participants, simulate


def test_single_elim_placements_8() -> None:
    bracket = simulate(pb.generate_single_elim(make_participants(8)))
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[1].position == 1
    assert placements[1].position_label == "1st"
    assert placements[2].position == 2
    # Losers of the quarterfinals occupy the 5-8 band.
    assert placements[5].position_label == "Top 8"


def test_single_elim_third_place() -> None:
    bracket = simulate(pb.generate_single_elim(make_participants(4), third_place_match=True))
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[3].position == 3
    assert placements[4].position == 4


def test_double_elim_placements_8() -> None:
    bracket = simulate(pb.generate_double_elim(make_participants(8)))
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[1].position == 1
    assert placements[2].position == 2
    assert placements[3].position == 3


def test_round_robin_placements_follow_standings() -> None:
    bracket = simulate(pb.generate_round_robin(make_participants(4)))
    placements = pb.get_placements(bracket)
    assert [p.participant_id for p in placements] == [1, 2, 3, 4]
    assert placements[0].position == 1
    assert placements[0].position_label == "1st"


def test_placement_records_elimination_round() -> None:
    bracket = simulate(pb.generate_single_elim(make_participants(8)))
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[2].eliminated_in == "Final"
    assert placements[1].eliminated_in == ""  # champion was never eliminated


@pytest.mark.parametrize("n", [4, 8, 16])
def test_every_participant_placed(n: int) -> None:
    bracket = simulate(pb.generate_single_elim(make_participants(n)))
    placed = {p.participant_id for p in pb.get_placements(bracket)}
    assert placed == {p.id for p in bracket.participants}
