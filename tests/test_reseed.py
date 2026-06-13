from __future__ import annotations

import pybracket as pb
import pytest

from tests.helpers import make_participants


def test_reseed_reorders_before_play() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    reseeded = pb.reseed(bracket, [4, 3, 2, 1])
    # The new seed 1 is the participant whose id is 4.
    seed_one = next(p for p in reseeded.participants if p.seed == 1)
    assert seed_one.id == 4
    first = [m for m in reseeded.matches if m.round_number == 1][0]
    assert first.participant1_id == 4


def test_reseed_rejects_after_play() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    m = pb.get_ready_matches(bracket)[0]
    bracket = pb.report_result(bracket, m.id, m.participant1_id)
    with pytest.raises(pb.BracketStateError):
        pb.reseed(bracket, [4, 3, 2, 1])


def test_reseed_requires_permutation() -> None:
    bracket = pb.generate_single_elim(make_participants(4))
    with pytest.raises(pb.ReseedError):
        pb.reseed(bracket, [1, 2, 3])  # missing a participant


def test_reseed_preserves_format_and_config() -> None:
    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=False)
    reseeded = pb.reseed(bracket, list(range(8, 0, -1)))
    assert reseeded.format == "double_elim"
    assert reseeded.config["grand_final_reset"] is False
