from __future__ import annotations

import pybracket as pb
from pybracket import BracketSide
from pybracket.naming.round_names import (
    gauntlet_round_name,
    ordinal,
    pool_label,
    pool_round_name,
)

from tests.helpers import make_participants


def _names(bracket: pb.Bracket, side: BracketSide) -> list[str]:
    return [r.name for r in bracket.rounds if r.bracket_side is side]


def test_single_elim_round_names() -> None:
    bracket = pb.generate_single_elim(make_participants(8))
    assert _names(bracket, BracketSide.WINNERS) == [
        "Quarterfinals",
        "Semifinals",
        "Final",
    ]


def test_single_elim_third_place_name() -> None:
    bracket = pb.generate_single_elim(make_participants(4), third_place_match=True)
    names = [r.name for r in bracket.rounds]
    assert "Third Place Match" in names


def test_double_elim_round_names() -> None:
    bracket = pb.generate_double_elim(make_participants(8))
    winners = _names(bracket, BracketSide.WINNERS)
    losers = _names(bracket, BracketSide.LOSERS)
    grand = _names(bracket, BracketSide.GRAND_FINAL)
    assert winners[-1] == "Winners Finals"
    assert losers[-1] == "Losers Finals"
    assert grand == ["Grand Final", "Grand Final Reset"]


def test_swiss_final_round_name() -> None:
    bracket = pb.generate_swiss(make_participants(8), rounds=3)
    assert bracket.rounds[0].name == "Round 1"
    # Play through to the last round and check its name.
    from tests.helpers import simulate

    bracket = simulate(bracket, advance_swiss=True)
    assert any(r.name == "Final Round" for r in bracket.rounds)


def test_single_gauntlet_final_name() -> None:
    bracket = pb.generate_gauntlet(make_participants(5), style="single")
    assert bracket.rounds[-1].name == "Final"


def test_ordinal() -> None:
    assert ordinal(1) == "1st"
    assert ordinal(2) == "2nd"
    assert ordinal(3) == "3rd"
    assert ordinal(4) == "4th"
    assert ordinal(11) == "11th"
    assert ordinal(21) == "21st"


def test_pool_label() -> None:
    assert pool_label(0) == "A"
    assert pool_label(1) == "B"
    assert pool_label(25) == "Z"
    assert pool_label(26) == "AA"


def test_pool_round_name() -> None:
    assert pool_round_name(0, 1) == "Pool A — Round 1"
    assert pool_round_name(2, 3) == "Pool C — Round 3"


def test_single_gauntlet_intermediate_round_name() -> None:
    # A non-final round of a single-sided gauntlet is just "Round N".
    assert gauntlet_round_name(2, total_rounds=4, style="single") == "Round 2"
    assert gauntlet_round_name(4, total_rounds=4, style="single") == "Final"


def test_dual_gauntlet_round_name_uses_single_elim_names() -> None:
    # A non-final dual-gauntlet round borrows the single-elim names (Semifinals, etc.).
    assert gauntlet_round_name(3, total_rounds=4, style="dual") == "Semifinals"
