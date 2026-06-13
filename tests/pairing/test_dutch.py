from __future__ import annotations

import pytest
from pybracket.pairing.dutch import dutch_order, dutch_pairings

from tests.helpers import make_participants


def test_round_one_top_half_vs_bottom_half() -> None:
    # Source: FIDE Handbook C.04.3 rule B/C.5 — within a homogeneous bracket S1 (top half)
    # is paired against S2 (bottom half): S1[i] vs S2[i].
    participants = make_participants(8)
    scores = {p.id: 0.0 for p in participants}
    pairings, bye = dutch_pairings(participants, scores, set(), set())
    assert bye is None
    assert pairings == [(1, 5), (2, 6), (3, 7), (4, 8)]


def test_dutch_order_interleaves_halves() -> None:
    participants = make_participants(8)
    scores = {p.id: 0.0 for p in participants}
    order = dutch_order(participants, scores)
    assert order == [1, 5, 2, 6, 3, 7, 4, 8]


def test_downfloat_on_odd_score_bracket() -> None:
    # Source: FIDE Handbook C.04.3 rule A.4 — the lowest player of an odd bracket downfloats.
    participants = make_participants(6)
    # Score bracket {1,2,3} (3 players, odd) and {4,5,6}.
    scores = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.0, 5: 0.0, 6: 0.0}
    order = dutch_order(participants, scores)
    # Player 3 downfloats and joins the lower bracket {3,4,5,6}.
    # Top bracket {1,2} pairs 1 vs 2; lower {3,4,5,6} pairs 3v5, 4v6.
    assert order[:2] == [1, 2]
    assert set(order[2:]) == {3, 4, 5, 6}


@pytest.mark.parametrize("n", [4, 8, 16])
def test_avoids_rematch(n: int) -> None:
    participants = make_participants(n)
    scores = {p.id: 0.0 for p in participants}
    first, _ = dutch_pairings(participants, scores, set(), set())
    played = {frozenset(p) for p in first}
    # Give the lower id the win to create score groups, then pair round 2.
    scores2 = dict.fromkeys((p.id for p in participants), 0.0)
    for a, b in first:
        scores2[min(a, b)] += 1.0
    second, _ = dutch_pairings(participants, scores2, played, set())
    second_pairs = {frozenset(p) for p in second}
    assert played.isdisjoint(second_pairs)


def test_bye_to_lowest() -> None:
    participants = make_participants(5)
    scores = {p.id: 0.0 for p in participants}
    _, bye = dutch_pairings(participants, scores, set(), set())
    assert bye == 5
