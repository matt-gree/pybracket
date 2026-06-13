from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import Bracket, BracketState, PairingMethod

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


def test_reseed_round_robin() -> None:
    bracket = pb.generate_round_robin(make_participants(4))
    reseeded = pb.reseed(bracket, [4, 3, 2, 1])
    assert reseeded.format == "round_robin"
    seed_one = next(p for p in reseeded.participants if p.seed == 1)
    assert seed_one.id == 4
    # A freshly reseeded round-robin is a fresh, unplayed schedule.
    assert pb.is_complete(reseeded) is False
    assert len(reseeded.matches) == 6  # C(4, 2)


def test_reseed_swiss_preserves_pairing_config() -> None:
    bracket = pb.generate_swiss(
        make_participants(8), rounds=3, pairing_method=PairingMethod.MONRAD
    )
    reseeded = pb.reseed(bracket, list(range(8, 0, -1)))
    assert reseeded.format == "swiss"
    assert reseeded.config["rounds"] == 3
    assert reseeded.config["pairing_method"] == PairingMethod.MONRAD


def test_reseed_single_gauntlet() -> None:
    bracket = pb.generate_gauntlet(make_participants(5), style="single")
    reseeded = pb.reseed(bracket, [5, 4, 3, 2, 1])
    assert reseeded.format == "gauntlet"
    assert reseeded.config["style"] == "single"


def test_reseed_dual_gauntlet() -> None:
    bracket = pb.generate_gauntlet(make_participants(6), style="dual")
    reseeded = pb.reseed(bracket, [6, 5, 4, 3, 2, 1])
    assert reseeded.format == "gauntlet"
    assert reseeded.config["style"] == "dual"


def test_reseed_unsupported_format_raises() -> None:
    bracket = Bracket(
        format="mystery",
        state=BracketState.DRAFT,
        participants=make_participants(2),
        matches=[],
        rounds=[],
        config={},
    )
    with pytest.raises(pb.ReseedError):
        pb.reseed(bracket, [2, 1])
