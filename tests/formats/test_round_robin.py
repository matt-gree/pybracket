from __future__ import annotations

from itertools import combinations

import pybracket as pb
import pytest
from pybracket import MatchStatus

from tests.helpers import make_participants, simulate


@pytest.mark.parametrize("n", [2, 3, 4, 5, 8])
def test_each_pair_plays_once(n: int) -> None:
    bracket = pb.generate_round_robin(make_participants(n))
    pairs = [
        frozenset((m.participant1_id, m.participant2_id))
        for m in bracket.matches
        if m.participant1_id is not None and m.participant2_id is not None
    ]
    assert len(pairs) == len(set(pairs)) == n * (n - 1) // 2
    expected = {frozenset(c) for c in combinations(range(1, n + 1), 2)}
    assert set(pairs) == expected


@pytest.mark.parametrize("n,rounds", [(4, 3), (8, 7), (5, 5), (3, 3)])
def test_round_count(n: int, rounds: int) -> None:
    bracket = pb.generate_round_robin(make_participants(n))
    assert len(bracket.rounds) == rounds


def test_odd_field_has_one_bye_per_round() -> None:
    bracket = pb.generate_round_robin(make_participants(5))
    bye_participants: list[int] = []
    for r in bracket.rounds:
        round_matches = [m for m in bracket.matches if m.id in r.match_ids]
        playing = {m.participant1_id for m in round_matches} | {m.participant2_id for m in round_matches}
        sitting = set(range(1, 6)) - {p for p in playing if p is not None}
        # A bye match (one participant) marks who sat out.
        assert len(sitting) <= 1
        byes = [m.winner_id for m in round_matches if m.status is MatchStatus.BYE]
        bye_participants.extend(byes)
    # The bye rotates through everyone exactly once.
    assert sorted(bye_participants) == [1, 2, 3, 4, 5]


def test_full_simulation_winner() -> None:
    bracket = pb.generate_round_robin(make_participants(4))
    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1
    standings = pb.get_standings(bracket)
    assert [s.participant_id for s in standings] == [1, 2, 3, 4]
    assert standings[0].wins == 3


def test_incomplete_midway() -> None:
    bracket = pb.generate_round_robin(make_participants(4))
    assert not pb.is_complete(bracket)
    ready = pb.get_ready_matches(bracket)
    bracket = pb.report_result(bracket, ready[0].id, ready[0].participant1_id)
    assert not pb.is_complete(bracket)
