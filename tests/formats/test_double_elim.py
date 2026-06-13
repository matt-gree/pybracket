from __future__ import annotations

import pybracket as pb
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pybracket import BracketSide, MatchStatus

from tests.helpers import make_participants, simulate


def _size(n: int) -> int:
    return 1 << (n - 1).bit_length()


@pytest.mark.parametrize("n", [4, 8, 16, 32])
def test_match_count(n: int) -> None:
    bracket = pb.generate_double_elim(make_participants(n))
    # WB (size-1) + LB (size-2) + grand final (1) + reset slot (1) = 2*size - 1.
    assert len(bracket.matches) == 2 * _size(n) - 1


def test_two_players_has_no_losers_bracket() -> None:
    bracket = pb.generate_double_elim(make_participants(2))
    assert all(m.bracket_side is BracketSide.WINNERS for m in bracket.matches)
    assert len(bracket.matches) == 1


@pytest.mark.parametrize("n", [8, 16])
def test_lb_round1_has_no_immediate_rematch(n: int) -> None:
    bracket = pb.generate_double_elim(make_participants(n))
    wb_r1 = [m for m in bracket.matches if m.bracket_side is BracketSide.WINNERS and m.round_number == 1]
    wb_pairs = {frozenset((m.participant1_id, m.participant2_id)) for m in wb_r1}
    for m in wb_r1:
        winner = min(m.participant1_id, m.participant2_id)
        bracket = pb.report_result(bracket, m.id, winner)
    lb_r1 = [m for m in bracket.matches if m.bracket_side is BracketSide.LOSERS and m.round_number == 1]
    for m in lb_r1:
        pair = frozenset((m.participant1_id, m.participant2_id))
        assert pair not in wb_pairs


def test_full_simulation_8() -> None:
    bracket = pb.generate_double_elim(make_participants(8))
    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1


def test_grand_final_reset_skipped_when_wb_finalist_wins() -> None:
    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    bracket = simulate(bracket)  # seed 1 wins the WB and the grand final outright
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    # The reset existed in the structure but was never required: NOT_NEEDED, not a bye and
    # not completed. No participant advanced through it.
    assert reset.status is MatchStatus.NOT_NEEDED
    assert reset.winner_id is None and reset.loser_id is None
    assert reset.participant1_id is None and reset.participant2_id is None
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1


def test_grand_final_reset_match_exists_from_generation_as_pending() -> None:
    # The reset slot is always part of the data model; it only settles to NOT_NEEDED later.
    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    assert reset.status is MatchStatus.PENDING


def test_not_needed_reset_survives_serialization() -> None:
    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    bracket = simulate(bracket)
    restored = pb.bracket_from_json(pb.bracket_to_json(bracket))
    assert restored == bracket
    reset = [m for m in restored.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    assert reset.status is MatchStatus.NOT_NEEDED


def test_grand_final_reset_activates_when_lb_finalist_wins() -> None:
    def decide(bracket: pb.Bracket, match: pb.Match) -> int:
        gf = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 1][0]
        completed_reset = any(
            m.bracket_side is BracketSide.GRAND_FINAL
            and m.round_number == 2
            and m.status is MatchStatus.COMPLETED
            for m in bracket.matches
        )
        if match.id == gf.id and not completed_reset:
            # The lower-bracket finalist (higher seed number here) takes the first set.
            return max(match.participant1_id, match.participant2_id)
        return min(match.participant1_id, match.participant2_id)

    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    bracket = simulate(bracket, decide)
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    assert reset.status is MatchStatus.COMPLETED


def test_grand_final_reset_false_completes_immediately() -> None:
    def decide(bracket: pb.Bracket, match: pb.Match) -> int:
        gf = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 1][0]
        if match.id == gf.id:
            return max(match.participant1_id, match.participant2_id)
        return min(match.participant1_id, match.participant2_id)

    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=False)
    bracket = simulate(bracket, decide)
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    # With the reset disabled, the first set is decisive and the reset slot closes as
    # NOT_NEEDED regardless of who wins it.
    assert reset.status is MatchStatus.NOT_NEEDED
    assert pb.is_complete(bracket)


@pytest.mark.parametrize("n", [8, 16])
def test_placement_bands(n: int) -> None:
    bracket = pb.generate_double_elim(make_participants(n))
    bracket = simulate(bracket)
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[1].position == 1
    assert placements[2].position == 2  # grand final loser
    assert placements[3].position == 3  # losers final loser


def test_ready_matches_never_includes_unfilled() -> None:
    # get_ready_matches must only return matches with both participants known (a known
    # brackets-manager.js bug for double elimination).
    bracket = pb.generate_double_elim(make_participants(8))
    guard = 0
    while not pb.is_complete(bracket):
        guard += 1
        assert guard < 200
        for m in pb.get_ready_matches(bracket):
            assert m.participant1_id is not None and m.participant2_id is not None
            assert m.status is MatchStatus.READY
        ready = pb.get_ready_matches(bracket)
        bracket = pb.report_result(bracket, ready[0].id, min(ready[0].participant1_id, ready[0].participant2_id))


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=4, max_value=32))
def test_every_participant_plays_at_least_two_matches(n: int) -> None:
    # Power-of-two fields have no byes: everyone gets a second chance before elimination.
    size = _size(n)
    if size != n:
        return
    bracket = pb.generate_double_elim(make_participants(n))
    bracket = simulate(bracket)
    appearances: dict[int, int] = {p.id: 0 for p in bracket.participants}
    for m in bracket.matches:
        if m.status is MatchStatus.COMPLETED:
            for pid in (m.participant1_id, m.participant2_id):
                if pid is not None:
                    appearances[pid] += 1
    assert all(count >= 2 for count in appearances.values())


def test_protected_seeds_separate_quarters() -> None:
    bracket = pb.generate_double_elim(make_participants(8), protected_seeds=4)
    assert bracket.config["protected_seeds"] == 4
    wb_round1 = [
        m
        for m in bracket.matches
        if m.round_number == 1 and m.bracket_side is BracketSide.WINNERS
    ]
    for m in wb_round1:
        top4 = {s for s in (m.participant1_id, m.participant2_id) if s in (1, 2, 3, 4)}
        assert len(top4) <= 1


def test_protected_seeds_full_simulation() -> None:
    bracket = pb.generate_double_elim(make_participants(8), protected_seeds=4)
    bracket = simulate(bracket)
    assert pb.get_winner(bracket).id == 1
