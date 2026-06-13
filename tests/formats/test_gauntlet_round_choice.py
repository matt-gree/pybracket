from __future__ import annotations

from typing import Any

import pybracket as pb
import pytest
from pybracket import MatchStatus

from tests.helpers import make_participants


def _gen(n: int) -> pb.Bracket:
    return pb.generate_gauntlet(
        make_participants(n), style="dual", opponent_choice=True, choice_scope="round"
    )


def _better_seed_wins(bracket: pb.Bracket, match: pb.Match) -> Any:
    p1 = pb.get_participant(bracket, match.participant1_id)
    p2 = pb.get_participant(bracket, match.participant2_id)
    return min((p1, p2), key=lambda p: p.seed).id


def _play(
    bracket: pb.Bracket,
    *,
    pick: str = "first",
    decide: Any = _better_seed_wins,
) -> pb.Bracket:
    """Drive a round-choice gauntlet to completion, resolving each choice as it opens."""
    guard = 0
    while not pb.is_complete(bracket):
        guard += 1
        assert guard < 300, "did not terminate"
        pending = [m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE]
        if pending:
            pool = pending[0].metadata["choice_pool"]
            bracket = pb.report_choice(
                bracket, pending[0].id, pool[0] if pick == "first" else pool[-1]
            )
            continue
        ready = pb.get_ready_matches(bracket)
        assert ready, "no choice pending and nothing ready"
        for m in ready:
            bracket = pb.report_result(bracket, m.id, decide(bracket, m))
    return bracket


def _semi_round(bracket: pb.Bracket) -> int:
    return max(m.round_number for m in bracket.matches) - 1


# --- structure -----------------------------------------------------------------------------


def test_seeds_one_and_two_seated_at_semifinals() -> None:
    bracket = _gen(8)
    semis = [m for m in bracket.matches if m.round_number == _semi_round(bracket)]
    assert len(semis) == 2
    seats = {m.participant1_id for m in semis}
    assert seats == {1, 2}


def test_choice_opens_immediately_at_bottom_for_even_field() -> None:
    # An even field feeds the two lowest seeds straight in, so the lowest choice is offered
    # at generation time (unlike semifinals scope, which waits for the lower bracket).
    bracket = _gen(8)
    pending = [m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE]
    assert len(pending) == 1
    chooser = pending[0]
    assert chooser.round_number == 1
    assert len(chooser.metadata["choice_pool"]) == 2


def test_odd_field_has_play_in_of_two_lowest_seeds() -> None:
    bracket = _gen(9)
    round1 = [m for m in bracket.matches if m.round_number == 1]
    assert len(round1) == 1  # a single play-in
    assert {round1[0].participant1_id, round1[0].participant2_id} == {8, 9}


@pytest.mark.parametrize("n", [4, 6, 8, 10, 16])
def test_choice_at_every_seated_level(n: int) -> None:
    # One chooser per seated level: (n // 2) - 1 for even fields, (n - 3) // 2 for odd.
    bracket = _gen(n)
    choosers = [m for m in bracket.matches if m.metadata.get("gauntlet_role") == "chooser"]
    expected = (n - 3) // 2 if n % 2 else n // 2 - 1
    assert len(choosers) == expected


def test_higher_seed_is_the_chooser_each_level() -> None:
    bracket = _gen(8)
    for chooser in (m for m in bracket.matches if m.metadata.get("gauntlet_role") == "chooser"):
        other = pb.get_match(bracket, chooser.metadata["choice_other_match"])
        # The chooser's seated seed is better (lower number) than the other seated seed.
        assert chooser.participant1_id < other.participant1_id


@pytest.mark.parametrize("n", [4, 5, 6, 7, 8, 9, 10, 12, 16])
def test_match_count_is_n_minus_one(n: int) -> None:
    assert len(_gen(n).matches) == n - 1


# --- choice semantics ----------------------------------------------------------------------


def test_report_choice_assigns_chosen_and_remainder() -> None:
    bracket = _gen(8)
    chooser = next(m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE)
    other_id = chooser.metadata["choice_other_match"]
    pool = list(chooser.metadata["choice_pool"])
    non_default = next(pid for pid in pool if pid != chooser.participant2_id)

    after = pb.report_choice(bracket, chooser.id, non_default)
    chooser_after = pb.get_match(after, chooser.id)
    other_after = pb.get_match(after, other_id)
    assert chooser_after.participant2_id == non_default
    assert other_after.participant2_id == (set(pool) - {non_default}).pop()
    assert chooser_after.status is MatchStatus.READY
    assert other_after.status is MatchStatus.READY


def test_report_choice_rejects_opponent_outside_pool() -> None:
    bracket = _gen(8)
    chooser = next(m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE)
    with pytest.raises(pb.InvalidResultError):
        pb.report_choice(bracket, chooser.id, 999)


def test_choices_cascade_upward_one_level_at_a_time() -> None:
    bracket = _gen(8)
    # Exactly one choice is ever open at a time; resolving and playing it reveals the next.
    seen_rounds = []
    guard = 0
    while not pb.is_complete(bracket):
        guard += 1
        assert guard < 100
        pending = [m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE]
        assert len(pending) <= 1
        if pending:
            seen_rounds.append(pending[0].round_number)
            bracket = pb.report_choice(bracket, pending[0].id, pending[0].metadata["choice_pool"][0])
            continue
        for m in pb.get_ready_matches(bracket):
            bracket = pb.report_result(bracket, m.id, _better_seed_wins(bracket, m))
    # Choices were offered bottom-up: rounds 1, 2, 3 in order.
    assert seen_rounds == [1, 2, 3]


# --- full runs -----------------------------------------------------------------------------


@pytest.mark.parametrize("n", [4, 5, 6, 7, 8, 9, 10, 12, 16])
@pytest.mark.parametrize("pick", ["first", "last"])
def test_full_run_completes_with_top_seed_champion(n: int, pick: str) -> None:
    # However the choices fall, when the better seed always wins the bracket completes and
    # seed 1 (never beatable here) is champion.
    bracket = _play(_gen(n), pick=pick)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1


def test_non_default_choices_still_complete() -> None:
    # Picking the non-default challenger at every level exercises the feeder-rewiring path.
    bracket = _play(_gen(16), pick="last")
    assert pb.is_complete(bracket)


# --- serialization / unwind / reseed -------------------------------------------------------


def test_mid_choice_round_trip() -> None:
    bracket = _gen(8)
    # Resolve the first choice and play round 1 to reach a fresh PENDING_CHOICE, then serialize.
    chooser = next(m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE)
    bracket = pb.report_choice(bracket, chooser.id, chooser.metadata["choice_pool"][0])
    for m in [m for m in bracket.matches if m.round_number == 1]:
        bracket = pb.report_result(bracket, m.id, _better_seed_wins(bracket, m))
    assert pb.bracket_from_dict(pb.bracket_to_dict(bracket)) == bracket
    assert pb.bracket_from_json(pb.bracket_to_json(bracket)) == bracket


def test_unwinding_a_feeder_recloses_open_choice() -> None:
    bracket = _gen(8)
    chooser = next(m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE)
    bracket = pb.report_choice(bracket, chooser.id, chooser.metadata["choice_pool"][0])
    round1 = [m for m in bracket.matches if m.round_number == 1]
    for m in round1:
        bracket = pb.report_result(bracket, m.id, _better_seed_wins(bracket, m))

    upper_chooser = next(
        m for m in bracket.matches if m.round_number == 2 and m.status is MatchStatus.PENDING_CHOICE
    )
    new, _ = pb.unwind_result(bracket, round1[0].id)
    reclosed = pb.get_match(new, upper_chooser.id)
    assert reclosed.status is MatchStatus.PENDING
    assert "choice_pool" not in reclosed.metadata

    # Replaying the feeder re-opens the same choice.
    replay = pb.get_match(new, round1[0].id)
    new = pb.report_result(new, replay.id, _better_seed_wins(new, replay))
    assert pb.get_match(new, upper_chooser.id).status is MatchStatus.PENDING_CHOICE


@pytest.mark.parametrize("n", [8, 9])
def test_deep_unwind_after_full_play_leaves_replayable_bracket(n: int) -> None:
    # Complete the bracket (taking the non-default challenger each time), unwind a round-1
    # result beneath every choice that was made, and confirm the bracket stays consistent and
    # can be replayed to a clean finish.
    bracket = _play(_gen(n), pick="last")
    assert pb.is_complete(bracket)
    round1 = [m for m in bracket.matches if m.round_number == 1 and m.status is MatchStatus.COMPLETED][0]
    new, _ = pb.unwind_result(bracket, round1.id)
    assert not pb.is_complete(new)
    for m in new.matches:
        if m.status is MatchStatus.COMPLETED:
            assert m.participant1_id is not None and m.participant2_id is not None
            assert m.winner_id in (m.participant1_id, m.participant2_id)
    new = _play(new, pick="first")
    assert pb.is_complete(new)
    assert pb.get_winner(new).id == 1


def test_reseed_preserves_round_choice_and_completes() -> None:
    bracket = _gen(8)
    reseeded = pb.reseed(bracket, [8, 7, 6, 5, 4, 3, 2, 1])
    assert reseeded.config["choice_scope"] == "round"
    assert reseeded.config["opponent_choice"] is True
    # The new seed 1 is participant 8, who now wins when the better seed always wins.
    reseeded = _play(reseeded)
    assert pb.get_winner(reseeded).id == 8


# --- contrast with semifinals scope --------------------------------------------------------


def test_round_scope_offers_more_choices_than_semifinals_scope() -> None:
    round_scope = _gen(8)
    semis_scope = pb.generate_gauntlet(
        make_participants(8), style="dual", opponent_choice=True, choice_scope="semifinals"
    )
    round_choosers = [m for m in round_scope.matches if m.metadata.get("gauntlet_role") == "chooser"]
    semi_choosers = [m for m in semis_scope.matches if m.metadata.get("gauntlet_role") == "chooser"]
    assert len(round_choosers) > len(semi_choosers) == 1
