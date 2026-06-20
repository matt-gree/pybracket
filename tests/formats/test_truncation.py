"""Truncated single-elimination (qualifier brackets that stop at a power-of-two top-N)."""

from __future__ import annotations

from collections import Counter

import pybracket as pb
import pytest

from tests.helpers import make_participants, simulate


def test_truncated_to_eight_plays_one_round() -> None:
    bracket = pb.generate_single_elim(make_participants(16), survivors=8)
    assert [r.name for r in bracket.rounds] == ["Round 1"]
    assert len(bracket.matches) == 8
    assert bracket.config["truncated_to"] == 8

    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket) is None  # co-survivors, no champion

    labels = Counter(p.position_label for p in pb.get_placements(bracket))
    assert labels == {"Top 8": 8, "Top 16": 8}


def test_truncated_to_four_plays_two_rounds() -> None:
    bracket = simulate(pb.generate_single_elim(make_participants(16), survivors=4))
    labels = Counter(p.position_label for p in pb.get_placements(bracket))
    assert labels == {"Top 4": 4, "Top 8": 4, "Top 16": 8}


def test_survivors_ranked_by_seed() -> None:
    # lower_seed_wins -> seeds 1..8 survive; they should rank 1..8 by seed.
    bracket = simulate(pb.generate_single_elim(make_participants(16), survivors=8))
    survivors = [p for p in pb.get_placements(bracket) if p.position_label == "Top 8"]
    survivors.sort(key=lambda p: p.position)
    assert [p.participant_id for p in survivors] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_no_champion_round_name_for_truncated_last_round() -> None:
    # The single played round of a 16-field qualifier is "Round 1", never "Final".
    bracket = pb.generate_single_elim(make_participants(16), survivors=8)
    assert all(r.name != "Final" for r in bracket.rounds)


def test_serialization_preserves_truncation() -> None:
    bracket = simulate(pb.generate_single_elim(make_participants(8), survivors=4))
    restored = pb.bracket_from_json(pb.bracket_to_json(bracket))
    assert restored.config["truncated_to"] == 4
    assert pb.get_winner(restored) is None
    labels = Counter(p.position_label for p in pb.get_placements(restored))
    assert labels == {"Top 4": 4, "Top 8": 4}


@pytest.mark.parametrize("bad", [3, 5, 1, 16, 32])
def test_invalid_survivors_rejected(bad: int) -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(16), survivors=bad)


def test_survivors_requires_power_of_two_field() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(12), survivors=8)  # 12 -> byes


def test_survivors_incompatible_with_third_place() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(16), survivors=8, third_place_match=True)


def test_survivors_incompatible_with_bye_rounds() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(
            make_participants(8), survivors=4, bye_rounds={1: 1, 2: 1, 3: 1, 4: 1}
        )


def test_survivors_incompatible_with_protected_seeds() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(16), survivors=8, protected_seeds=2)
