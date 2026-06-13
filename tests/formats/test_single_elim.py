from __future__ import annotations

import math

import pybracket as pb
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pybracket import BracketSide, MatchStatus

from tests.helpers import make_participants, simulate


def expected_match_count(n: int) -> int:
    size = 1 << (max(0, n - 1)).bit_length() if n > 1 else 1
    return size - 1


@pytest.mark.parametrize("n", [2, 3, 4, 5, 8, 16, 32])
def test_match_count(n: int) -> None:
    bracket = pb.generate_single_elim(make_participants(n))
    assert len(bracket.matches) == expected_match_count(n)


@pytest.mark.parametrize("n", [2, 3, 4, 5, 8, 16, 32])
def test_round_count(n: int) -> None:
    bracket = pb.generate_single_elim(make_participants(n))
    size = 1 << (n - 1).bit_length()
    assert len(bracket.rounds) == int(math.log2(size))


@pytest.mark.parametrize("n", [3, 5, 6, 7])
def test_top_seeds_receive_byes(n: int) -> None:
    bracket = pb.generate_single_elim(make_participants(n))
    size = 1 << (n - 1).bit_length()
    bye_count = size - n
    # The participants who advanced via a BYE in round 1 must be the top `bye_count` seeds.
    bye_winners = {
        m.winner_id
        for m in bracket.matches
        if m.status is MatchStatus.BYE and m.round_number == 1 and m.winner_id is not None
    }
    assert bye_winners == set(range(1, bye_count + 1))


def test_full_tournament_simulation_8() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    assert not pb.is_complete(bracket)
    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[1].position == 1
    assert placements[2].position == 2


def test_third_place_match() -> None:
    bracket = pb.generate_single_elim(make_participants(4), third_place_match=True)
    third = [m for m in bracket.matches if m.metadata.get("consolation")]
    assert len(third) == 1
    bracket = simulate(bracket)
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[3].position == 3
    assert placements[3].position_label == "3rd"
    assert placements[4].position == 4


def test_no_loser_pointer_without_third_place() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    assert all(m.next_loser_match_id is None for m in bracket.matches)


def test_ready_matches_progression() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    ready = pb.get_ready_matches(bracket)
    assert len(ready) == 2  # both semifinals
    bracket = pb.report_result(bracket, ready[0].id, ready[0].participant1_id)
    # Final still pending until the other semifinal resolves.
    assert all(m.bracket_side is BracketSide.WINNERS for m in pb.get_ready_matches(bracket))
    assert len(pb.get_ready_matches(bracket)) == 1


def test_protected_seeds_separate_quarters() -> None:
    bracket = pb.generate_single_elim(make_participants(8), protected_seeds=4)
    # Seeds 1-4 must not meet before the semifinals: check they are in distinct quarters.
    round1 = [m for m in bracket.matches if m.round_number == 1]
    for m in round1:
        slots = {m.participant1_id, m.participant2_id}
        top4 = {s for s in slots if s in (1, 2, 3, 4)}
        assert len(top4) <= 1


@given(st.integers(min_value=2, max_value=64))
def test_match_count_property(n: int) -> None:
    bracket = pb.generate_single_elim(make_participants(n))
    assert len(bracket.matches) == expected_match_count(n)


@given(st.integers(min_value=2, max_value=64))
def test_top_seed_at_slot_one(n: int) -> None:
    bracket = pb.generate_single_elim(make_participants(n))
    first_match = [m for m in bracket.matches if m.round_number == 1][0]
    assert first_match.participant1_id == 1  # seed 1 occupies the first slot
