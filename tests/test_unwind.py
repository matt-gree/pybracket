from __future__ import annotations

import pybracket as pb
from pybracket import MatchStatus

from tests.helpers import make_participants


def test_unwind_no_downstream_match() -> None:
    # A 2-player single match has no downstream.
    bracket = pb.generate_single_elim(make_participants(2))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id, metadata={"g": 1})
    assert pb.is_complete(bracket)
    new, signals = pb.unwind_result(bracket, m.id)
    assert pb.get_match(new, m.id).status is MatchStatus.READY
    assert pb.get_match(new, m.id).winner_id is None
    assert [s.match_id for s in signals] == [m.id]
    assert signals[0].metadata == {"g": 1}


def test_unwind_with_unplayed_downstream() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    semis = pb.get_ready_matches(bracket)
    bracket = pb.report_result(bracket, semis[0].id, semis[0].participant1_id)
    final = [m for m in bracket.matches if m.round_number == 2][0]
    assert final.participant1_id == semis[0].participant1_id
    new, signals = pb.unwind_result(bracket, semis[0].id)
    # The semifinal winner is removed from the (unplayed) final.
    final_after = [m for m in new.matches if m.round_number == 2][0]
    assert semis[0].participant1_id not in (final_after.participant1_id, final_after.participant2_id)
    assert len(signals) == 1


def test_unwind_cascades_into_played_downstream() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    semis = pb.get_ready_matches(bracket)
    bracket = pb.report_result(bracket, semis[0].id, semis[0].participant1_id, metadata={"g": "s1"})
    bracket = pb.report_result(bracket, semis[1].id, semis[1].participant1_id, metadata={"g": "s2"})
    final = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, final.id, final.participant1_id, metadata={"g": "final"})
    assert pb.is_complete(bracket)
    new, signals = pb.unwind_result(bracket, semis[0].id)
    ids = {s.match_id for s in signals}
    assert semis[0].id in ids
    assert final.id in ids  # cascaded
    assert not pb.is_complete(new)
    assert pb.get_match(new, final.id).status in (MatchStatus.READY, MatchStatus.PENDING)


def test_unwind_three_levels_deep() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    from tests.helpers import simulate

    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    # Unwind a round-1 match; it should cascade through the player's whole winning path.
    r1 = [m for m in bracket.matches if m.round_number == 1 and m.winner_id == 1][0]
    new, signals = pb.unwind_result(bracket, r1.id)
    # Seed 1 won rounds 1, 2, 3 (final) -> all three cascade.
    assert len(signals) >= 3
    assert not pb.is_complete(new)


def test_bracket_playable_after_unwind() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    semis = pb.get_ready_matches(bracket)
    bracket = pb.report_result(bracket, semis[0].id, semis[0].participant1_id)
    new, _ = pb.unwind_result(bracket, semis[0].id)
    # The unwound match is ready again with both participants intact.
    again = pb.get_match(new, semis[0].id)
    assert again.status is MatchStatus.READY
    assert again.participant1_id is not None and again.participant2_id is not None
    # And we can re-report it.
    re = pb.report_result(new, semis[0].id, semis[0].participant2_id)
    assert pb.get_match(re, semis[0].id).winner_id == semis[0].participant2_id


def test_unwind_grand_final_deactivates_reset() -> None:
    from pybracket import BracketSide

    def decide(bracket: pb.Bracket, match: pb.Match) -> int:
        gf = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 1][0]
        done_reset = any(
            m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2 and m.status is MatchStatus.COMPLETED
            for m in bracket.matches
        )
        if match.id == gf.id and not done_reset:
            return max(match.participant1_id, match.participant2_id)
        return min(match.participant1_id, match.participant2_id)


    bracket = pb.generate_double_elim(make_participants(4), grand_final_reset=True)
    # Play up to (and including) the grand final, activating the reset.
    from pybracket import BracketSide as BS

    guard = 0
    gf_id = None
    while not pb.is_complete(bracket):
        guard += 1
        assert guard < 100
        ready = pb.get_ready_matches(bracket)
        reset = [m for m in bracket.matches if m.bracket_side is BS.GRAND_FINAL and m.round_number == 2][0]
        if reset.status is MatchStatus.READY:
            gf = [m for m in bracket.matches if m.bracket_side is BS.GRAND_FINAL and m.round_number == 1][0]
            gf_id = gf.id
            break
        for m in ready:
            bracket = pb.report_result(bracket, m.id, decide(bracket, m))
    assert gf_id is not None
    new, _ = pb.unwind_result(bracket, gf_id)
    reset = [m for m in new.matches if m.bracket_side is BS.GRAND_FINAL and m.round_number == 2][0]
    assert reset.status is MatchStatus.PENDING
    assert reset.participant1_id is None and reset.participant2_id is None
