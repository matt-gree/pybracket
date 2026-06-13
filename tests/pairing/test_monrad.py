from __future__ import annotations

import pytest
from pybracket.pairing.monrad import monrad_pairings, rank_participants

from tests.helpers import make_participants


@pytest.mark.parametrize("n", [4, 8, 16])
def test_round_one_pairs_adjacent(n: int) -> None:
    participants = make_participants(n)
    scores = {p.id: 0.0 for p in participants}
    pairings, bye = monrad_pairings(participants, scores, set(), set())
    assert bye is None
    # With equal scores Monrad pairs by rank: (1,2), (3,4), ...
    assert pairings == [(2 * i + 1, 2 * i + 2) for i in range(n // 2)]


def test_bye_to_lowest_without_bye() -> None:
    participants = make_participants(5)
    scores = {p.id: 0.0 for p in participants}
    _, bye = monrad_pairings(participants, scores, set(), set())
    assert bye == 5  # lowest seed (rank) gets the first bye


def test_bye_not_repeated() -> None:
    participants = make_participants(5)
    scores = {p.id: 0.0 for p in participants}
    _, bye = monrad_pairings(participants, scores, set(), had_bye={5})
    assert bye == 4  # seed 5 already had one, next lowest gets it


def test_avoids_rematch() -> None:
    participants = make_participants(4)
    scores = {1: 1.0, 2: 1.0, 3: 0.0, 4: 0.0}
    played = {frozenset((1, 2)), frozenset((3, 4))}
    pairings, _ = monrad_pairings(participants, scores, played, set())
    pairs = {frozenset(p) for p in pairings}
    assert played.isdisjoint(pairs)


def test_rank_by_score_then_seed() -> None:
    participants = make_participants(4)
    scores = {1: 0.0, 2: 2.0, 3: 1.0, 4: 1.0}
    ranked = rank_participants(participants, scores)
    assert [p.id for p in ranked] == [2, 3, 4, 1]


def test_odd_field_without_byes_raises() -> None:
    participants = make_participants(5)
    scores = {p.id: 0.0 for p in participants}
    with pytest.raises(ValueError):
        monrad_pairings(participants, scores, set(), set(), allow_bye=False)


def test_bye_when_everyone_already_had_one() -> None:
    # When every remaining player has already had a bye, the lowest-ranked still takes it.
    participants = make_participants(5)
    scores = {p.id: 0.0 for p in participants}
    _, bye = monrad_pairings(participants, scores, set(), had_bye={1, 2, 3, 4, 5})
    assert bye == 5


def test_falls_back_when_no_rematch_free_pairing() -> None:
    # Every possible pair has already been played: backtracking fails, so we fall back to a
    # plain nearest-neighbour pairing rather than crashing.
    participants = make_participants(4)
    scores = {p.id: 0.0 for p in participants}
    played = {
        frozenset((1, 2)), frozenset((1, 3)), frozenset((1, 4)),
        frozenset((2, 3)), frozenset((2, 4)), frozenset((3, 4)),
    }
    pairings, bye = monrad_pairings(participants, scores, played, set())
    assert bye is None
    assert pairings == [(1, 2), (3, 4)]
