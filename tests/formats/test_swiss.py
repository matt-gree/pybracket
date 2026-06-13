from __future__ import annotations

import math

import pybracket as pb
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pybracket import MatchStatus, PairingMethod
from pybracket.tiebreakers.base import StandingsContext

from tests.helpers import make_participants


def _play_round(bracket: pb.Bracket) -> pb.Bracket:
    for m in pb.get_ready_matches(bracket):
        bracket = pb.report_result(bracket, m.id, min(m.participant1_id, m.participant2_id))
    return bracket


def _run_full_swiss(n: int, method: PairingMethod) -> pb.Bracket:
    bracket = pb.generate_swiss(make_participants(n), pairing_method=method)
    bracket = _play_round(bracket)
    while not pb.is_complete(bracket):
        bracket = pb.advance_swiss_round(bracket)
        bracket = _play_round(bracket)
    return bracket


@pytest.mark.parametrize("n", range(2, 257))
def test_recommend_swiss_rounds(n: int) -> None:
    assert pb.recommend_swiss_rounds(n) == math.ceil(math.log2(n))


@pytest.mark.parametrize("method", [PairingMethod.MONRAD, PairingMethod.DUTCH])
@pytest.mark.parametrize("n", [4, 8, 16, 32])
def test_no_rematches(n: int, method: PairingMethod) -> None:
    bracket = _run_full_swiss(n, method)
    pairs: list[frozenset[int]] = []
    for m in bracket.matches:
        if m.participant1_id is not None and m.participant2_id is not None:
            pairs.append(frozenset((m.participant1_id, m.participant2_id)))
    assert len(pairs) == len(set(pairs)), "a pairing was repeated"


@pytest.mark.parametrize("method", [PairingMethod.MONRAD, PairingMethod.DUTCH])
def test_bye_rotation_no_double_byes(method: PairingMethod) -> None:
    bracket = _run_full_swiss(5, method)
    bye_recipients = [
        m.winner_id for m in bracket.matches if m.status is MatchStatus.BYE
    ]
    assert len(bye_recipients) == len(set(bye_recipients)), "a player received two byes"


def test_advance_raises_when_round_incomplete() -> None:
    bracket = pb.generate_swiss(make_participants(8))
    with pytest.raises(pb.SwissRoundIncompleteError):
        pb.advance_swiss_round(bracket)


def test_advance_raises_when_all_rounds_generated() -> None:
    bracket = pb.generate_swiss(make_participants(4), rounds=1)
    bracket = _play_round(bracket)
    assert pb.is_complete(bracket)
    with pytest.raises(pb.BracketStateError):
        pb.advance_swiss_round(bracket)


@pytest.mark.parametrize("method", [PairingMethod.MONRAD, PairingMethod.DUTCH])
def test_pairs_within_score_groups(method: PairingMethod) -> None:
    # After round 1, round 2 should pair players whose scores differ by at most one.
    bracket = pb.generate_swiss(make_participants(8), pairing_method=method)
    bracket = _play_round(bracket)
    bracket = pb.advance_swiss_round(bracket)
    ctx = StandingsContext(
        [m for m in bracket.matches if m.round_number == 1], [p.id for p in bracket.participants]
    )
    round2 = [m for m in bracket.matches if m.round_number == 2 and m.participant2_id is not None]
    for m in round2:
        assert abs(ctx.wins[m.participant1_id] - ctx.wins[m.participant2_id]) <= 1


def test_round_count_uses_recommendation() -> None:
    bracket = pb.generate_swiss(make_participants(8))
    assert bracket.config["rounds"] == 3


def test_explicit_round_count() -> None:
    bracket = pb.generate_swiss(make_participants(8), rounds=5)
    assert bracket.config["rounds"] == 5


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    n=st.sampled_from([4, 8, 16, 32]),
    method=st.sampled_from([PairingMethod.MONRAD, PairingMethod.DUTCH]),
    coin=st.lists(st.booleans(), min_size=200, max_size=200),
)
def test_no_rematches_with_random_results(
    n: int, method: PairingMethod, coin: list[bool]
) -> None:
    # Property: no pairing is ever repeated regardless of how results fall (invariant test).
    flips = iter(coin)

    def decide(bracket: pb.Bracket, match: pb.Match) -> int:
        try:
            pick_first = next(flips)
        except StopIteration:
            pick_first = True
        return match.participant1_id if pick_first else match.participant2_id

    bracket = pb.generate_swiss(make_participants(n), pairing_method=method)
    while True:
        for m in pb.get_ready_matches(bracket):
            bracket = pb.report_result(bracket, m.id, decide(bracket, m))
        if pb.is_complete(bracket):
            break
        bracket = pb.advance_swiss_round(bracket)

    pairs = [
        frozenset((m.participant1_id, m.participant2_id))
        for m in bracket.matches
        if m.participant1_id is not None and m.participant2_id is not None
    ]
    assert len(pairs) == len(set(pairs))
