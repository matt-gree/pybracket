from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import MatchStatus

from tests.helpers import make_participants, simulate


@pytest.mark.parametrize("n", [3, 4, 5, 8])
def test_single_gauntlet_is_linear_chain(n: int) -> None:
    bracket = pb.generate_gauntlet(make_participants(n), style="single")
    assert len(bracket.matches) == n - 1
    for r in bracket.rounds:
        assert len(r.match_ids) == 1
    chain = sorted(bracket.matches, key=lambda m: m.round_number)
    for i in range(len(chain) - 1):
        assert chain[i].next_winner_match_id == chain[i + 1].id
    assert chain[-1].next_winner_match_id is None


def test_single_gauntlet_seed1_plays_one_match() -> None:
    bracket = pb.generate_gauntlet(make_participants(8), style="single")
    bracket = simulate(bracket)
    appearances = sum(
        1 for m in bracket.matches if 1 in (m.participant1_id, m.participant2_id)
    )
    assert appearances == 1  # seed 1 only enters at the final
    assert pb.get_winner(bracket).id == 1


def test_single_gauntlet_round1_lowest_seeds() -> None:
    n = 6
    bracket = pb.generate_gauntlet(make_participants(n), style="single")
    first = [m for m in bracket.matches if m.round_number == 1][0]
    assert {first.participant1_id, first.participant2_id} == {n, n - 1}


def test_single_gauntlet_rejects_opponent_choice() -> None:
    # A single ladder has no opponent to choose — the next foe is always the next seed.
    with pytest.raises(pb.ValidationError):
        pb.generate_gauntlet(make_participants(5), style="single", opponent_choice=True)


def _semi_round(bracket: pb.Bracket) -> int:
    return max(m.round_number for m in bracket.matches) - 1


def test_dual_gauntlet_seeds_enter_at_semifinals() -> None:
    bracket = pb.generate_gauntlet(make_participants(8), style="dual")
    round1 = [m for m in bracket.matches if m.round_number == 1]
    in_round1 = {x for m in round1 for x in (m.participant1_id, m.participant2_id) if x}
    assert 1 not in in_round1 and 2 not in in_round1  # top seeds are byed past round 1

    semis = [m for m in bracket.matches if m.round_number == _semi_round(bracket)]
    assert len(semis) == 2
    # Seeds 1 and 2 occupy different semifinals (opposite sides of the bracket).
    sf_with_1 = next(m for m in semis if 1 in (m.participant1_id, m.participant2_id))
    sf_with_2 = next(m for m in semis if 2 in (m.participant1_id, m.participant2_id))
    assert sf_with_1.id != sf_with_2.id


def test_dual_gauntlet_completes() -> None:
    bracket = pb.generate_gauntlet(make_participants(8), style="dual")
    bracket = simulate(bracket)
    assert pb.get_winner(bracket).id == 1


@pytest.mark.parametrize("n", [2, 3, 4, 5, 8])
def test_dual_gauntlet_completes_various_sizes(n: int) -> None:
    bracket = pb.generate_gauntlet(make_participants(n), style="dual")
    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket) is not None


@pytest.mark.parametrize("n", [4, 6, 8, 9, 10, 12, 14, 16, 24])
def test_dual_gauntlet_stays_two_games_per_round(n: int) -> None:
    # A double gauntlet is two climbing ladders: it must never widen into a regular bracket,
    # so no round ever holds more than two games regardless of field size.
    bracket = pb.generate_gauntlet(make_participants(n), style="dual")
    for r in bracket.rounds:
        assert len(r.match_ids) <= 2
    assert len(bracket.matches) == n - 1


def test_dual_gauntlet_two_players_is_single_final() -> None:
    bracket = pb.generate_gauntlet(make_participants(2), style="dual")
    assert len(bracket.matches) == 1
    assert bracket.rounds[-1].name == "Final"


def test_dual_gauntlet_three_players_byes_one_semifinalist() -> None:
    # Seeds 1 and 2 enter at the semis; the lone lower seed (3) faces seed 1 while seed 2
    # gets a bye into the final.
    bracket = pb.generate_gauntlet(make_participants(3), style="dual")
    bracket = simulate(bracket)
    assert pb.get_winner(bracket).id == 1


def test_unknown_gauntlet_style_rejected() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_gauntlet(make_participants(4), style="triple")  # type: ignore[arg-type]


def _advance_until_choice(bracket: pb.Bracket) -> pb.Bracket:
    guard = 0
    while True:
        guard += 1
        assert guard < 100
        if any(m.status is MatchStatus.PENDING_CHOICE for m in bracket.matches):
            return bracket
        ready = pb.get_ready_matches(bracket)
        assert ready, "no choice pending and nothing ready"
        for m in ready:
            bracket = pb.report_result(bracket, m.id, min(m.participant1_id, m.participant2_id))


def test_dual_opponent_choice_offers_both_survivors() -> None:
    bracket = pb.generate_gauntlet(
        make_participants(8), style="dual", opponent_choice=True, choice_scope="semifinals"
    )
    # No choice until both lower-bracket survivors are known.
    assert not any(m.status is MatchStatus.PENDING_CHOICE for m in bracket.matches)
    bracket = _advance_until_choice(bracket)
    chooser = next(m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE)
    # Seed 1 is the chooser and has two survivors to pick from.
    assert 1 in (chooser.participant1_id, chooser.participant2_id)
    assert len(chooser.metadata["choice_pool"]) == 2


def test_dual_opponent_choice_swaps_survivor() -> None:
    bracket = pb.generate_gauntlet(
        make_participants(8), style="dual", opponent_choice=True, choice_scope="semifinals"
    )
    bracket = _advance_until_choice(bracket)
    chooser = next(m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE)
    other_id = chooser.metadata["choice_other_match"]
    pool = list(chooser.metadata["choice_pool"])
    non_default = next(pid for pid in pool if pid != chooser.participant2_id)

    after = pb.report_choice(bracket, chooser.id, non_default)
    chooser_after = pb.get_match(after, chooser.id)
    other_after = pb.get_match(after, other_id)
    # Seed 1 now faces the chosen survivor; seed 2 gets the other one.
    assert non_default in (chooser_after.participant1_id, chooser_after.participant2_id)
    assert chooser_after.status is MatchStatus.READY
    assert other_after.status is MatchStatus.READY


def test_dual_opponent_choice_full_run() -> None:
    bracket = pb.generate_gauntlet(
        make_participants(8), style="dual", opponent_choice=True, choice_scope="semifinals"
    )
    guard = 0
    while not pb.is_complete(bracket):
        guard += 1
        assert guard < 100
        pending = [m for m in bracket.matches if m.status is MatchStatus.PENDING_CHOICE]
        if pending:
            m = pending[0]
            bracket = pb.report_choice(bracket, m.id, m.metadata["choice_pool"][0])
            continue
        ready = pb.get_ready_matches(bracket)
        for m in ready:
            bracket = pb.report_result(bracket, m.id, min(m.participant1_id, m.participant2_id))
    assert pb.get_winner(bracket) is not None


def test_state_draft_builds_without_locking() -> None:
    for kwargs in ({"style": "single"}, {"style": "dual"},
                   {"style": "dual", "opponent_choice": True}):
        draft = pb.generate_gauntlet(
            make_participants(6), state=pb.BracketState.DRAFT, **kwargs
        )
        assert draft.state is pb.BracketState.DRAFT
        assert len(draft.matches) > 0
        published = pb.generate_gauntlet(make_participants(6), **kwargs)
        assert published.state is pb.BracketState.PUBLISHED
        # Opponent-choice frontiers are still set up in DRAFT.
        if kwargs.get("opponent_choice"):
            statuses = {m.status for m in draft.matches}
            assert pb.MatchStatus.PENDING_CHOICE in statuses
