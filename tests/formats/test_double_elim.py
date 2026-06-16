from __future__ import annotations

from collections import Counter
from collections.abc import Callable

import pybracket as pb
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pybracket import BracketSide, MatchStatus
from pybracket.advancement.engine import compute_occupant_counts
from pybracket.formats.double_elim import MAX_DOUBLE_ELIM_BYE_LEVEL

from tests.helpers import make_participants, simulate


def _size(n: int) -> int:
    return 1 << (n - 1).bit_length()


@pytest.mark.parametrize("n", [4, 8, 16, 32])
def test_match_count(n: int) -> None:
    bracket = pb.generate_double_elim(make_participants(n))
    # WB (size-1) + LB (size-2) + grand final (1) + reset slot (1) = 2*size - 1.
    assert len(bracket.matches) == 2 * _size(n) - 1


def test_two_players_has_no_losers_bracket() -> None:
    bracket = pb.generate_double_elim(make_participants(2))
    assert all(m.bracket_side is BracketSide.WINNERS for m in bracket.matches)
    assert len(bracket.matches) == 1


@pytest.mark.parametrize("n", [8, 16])
def test_lb_round1_has_no_immediate_rematch(n: int) -> None:
    bracket = pb.generate_double_elim(make_participants(n))
    wb_r1 = [m for m in bracket.matches if m.bracket_side is BracketSide.WINNERS and m.round_number == 1]
    wb_pairs = {frozenset((m.participant1_id, m.participant2_id)) for m in wb_r1}
    for m in wb_r1:
        winner = min(m.participant1_id, m.participant2_id)
        bracket = pb.report_result(bracket, m.id, winner)
    lb_r1 = [m for m in bracket.matches if m.bracket_side is BracketSide.LOSERS and m.round_number == 1]
    for m in lb_r1:
        pair = frozenset((m.participant1_id, m.participant2_id))
        assert pair not in wb_pairs


def test_full_simulation_8() -> None:
    bracket = pb.generate_double_elim(make_participants(8))
    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1


def test_grand_final_reset_skipped_when_wb_finalist_wins() -> None:
    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    bracket = simulate(bracket)  # seed 1 wins the WB and the grand final outright
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    # The reset existed in the structure but was never required: NOT_NEEDED, not a bye and
    # not completed. No participant advanced through it.
    assert reset.status is MatchStatus.NOT_NEEDED
    assert reset.winner_id is None and reset.loser_id is None
    assert reset.participant1_id is None and reset.participant2_id is None
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1


def test_grand_final_reset_match_exists_from_generation_as_pending() -> None:
    # The reset slot is always part of the data model; it only settles to NOT_NEEDED later.
    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    assert reset.status is MatchStatus.PENDING


def test_not_needed_reset_survives_serialization() -> None:
    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    bracket = simulate(bracket)
    restored = pb.bracket_from_json(pb.bracket_to_json(bracket))
    assert restored == bracket
    reset = [m for m in restored.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    assert reset.status is MatchStatus.NOT_NEEDED


def test_grand_final_reset_activates_when_lb_finalist_wins() -> None:
    def decide(bracket: pb.Bracket, match: pb.Match) -> int:
        gf = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 1][0]
        completed_reset = any(
            m.bracket_side is BracketSide.GRAND_FINAL
            and m.round_number == 2
            and m.status is MatchStatus.COMPLETED
            for m in bracket.matches
        )
        if match.id == gf.id and not completed_reset:
            # The lower-bracket finalist (higher seed number here) takes the first set.
            return max(match.participant1_id, match.participant2_id)
        return min(match.participant1_id, match.participant2_id)

    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=True)
    bracket = simulate(bracket, decide)
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    assert reset.status is MatchStatus.COMPLETED


def test_grand_final_reset_false_completes_immediately() -> None:
    def decide(bracket: pb.Bracket, match: pb.Match) -> int:
        gf = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 1][0]
        if match.id == gf.id:
            return max(match.participant1_id, match.participant2_id)
        return min(match.participant1_id, match.participant2_id)

    bracket = pb.generate_double_elim(make_participants(8), grand_final_reset=False)
    bracket = simulate(bracket, decide)
    reset = [m for m in bracket.matches if m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2][0]
    # With the reset disabled, the first set is decisive and the reset slot closes as
    # NOT_NEEDED regardless of who wins it.
    assert reset.status is MatchStatus.NOT_NEEDED
    assert pb.is_complete(bracket)


@pytest.mark.parametrize("n", [8, 16])
def test_placement_bands(n: int) -> None:
    bracket = pb.generate_double_elim(make_participants(n))
    bracket = simulate(bracket)
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[1].position == 1
    assert placements[2].position == 2  # grand final loser
    assert placements[3].position == 3  # losers final loser


def test_ready_matches_never_includes_unfilled() -> None:
    # get_ready_matches must only return matches with both participants known (a known
    # brackets-manager.js bug for double elimination).
    bracket = pb.generate_double_elim(make_participants(8))
    guard = 0
    while not pb.is_complete(bracket):
        guard += 1
        assert guard < 200
        for m in pb.get_ready_matches(bracket):
            assert m.participant1_id is not None and m.participant2_id is not None
            assert m.status is MatchStatus.READY
        ready = pb.get_ready_matches(bracket)
        bracket = pb.report_result(bracket, ready[0].id, min(ready[0].participant1_id, ready[0].participant2_id))


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=4, max_value=32))
def test_every_participant_plays_at_least_two_matches(n: int) -> None:
    # Power-of-two fields have no byes: everyone gets a second chance before elimination.
    size = _size(n)
    if size != n:
        return
    bracket = pb.generate_double_elim(make_participants(n))
    bracket = simulate(bracket)
    appearances: dict[int, int] = {p.id: 0 for p in bracket.participants}
    for m in bracket.matches:
        if m.status is MatchStatus.COMPLETED:
            for pid in (m.participant1_id, m.participant2_id):
                if pid is not None:
                    appearances[pid] += 1
    assert all(count >= 2 for count in appearances.values())


def test_protected_seeds_separate_quarters() -> None:
    bracket = pb.generate_double_elim(make_participants(8), protected_seeds=4)
    assert bracket.config["protected_seeds"] == 4
    wb_round1 = [
        m
        for m in bracket.matches
        if m.round_number == 1 and m.bracket_side is BracketSide.WINNERS
    ]
    for m in wb_round1:
        top4 = {s for s in (m.participant1_id, m.participant2_id) if s in (1, 2, 3, 4)}
        assert len(top4) <= 1


def test_protected_seeds_full_simulation() -> None:
    bracket = pb.generate_double_elim(make_participants(8), protected_seeds=4)
    bracket = simulate(bracket)
    assert pb.get_winner(bracket).id == 1


# --- custom byes (<= double) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "n, bye_rounds",
    [
        (12, {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 1, 8: 1}),  # 6x double, 2x single
        (11, dict.fromkeys(range(1, 8), 2)),  # 7x double
        (6, {1: 1, 2: 1}),  # standard single byes, requested explicitly
    ],
)
def test_bye_rounds_build_and_simulate(n: int, bye_rounds: dict[int, int]) -> None:
    bracket = pb.generate_double_elim(make_participants(n), bye_rounds=bye_rounds)
    assert "bye_rounds" in bracket.config
    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1


def test_bye_rounds_double_byed_seed_enters_third_round() -> None:
    # Seed 1 gets a double bye: its first *real* (non-bye) winners match is in round 3.
    bracket = pb.generate_double_elim(
        make_participants(12), bye_rounds={1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 1, 8: 1}
    )
    real_rounds = [
        m.round_number
        for m in bracket.matches
        if m.bracket_side is BracketSide.WINNERS
        and m.status is not MatchStatus.BYE
        and 1 in (m.participant1_id, m.participant2_id)
    ]
    assert min(real_rounds) == 3


def test_bye_rounds_rejects_triple() -> None:
    # A triple bye tiles for n=10 but exceeds double elimination's supported depth.
    with pytest.raises(pb.ValidationError):
        pb.generate_double_elim(
            make_participants(10), bye_rounds={1: 3, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2}
        )


def test_bye_rounds_rejects_protected_seeds_combo() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_double_elim(make_participants(12), bye_rounds={1: 1, 2: 1}, protected_seeds=4)


# --- bye collapse (compact structure, no phantom matches) ----------------------------------

_CUSTOM_14 = {1: 2, 2: 2, 3: 2, **dict.fromkeys(range(4, 13), 1)}


def test_byes_collapse_to_compact_bracket() -> None:
    # A byed double elim has no bye/phantom matches at all, and its losers bracket starts at
    # round 1 (not mid-bracket) — the reported "disconnected, no losers round 1" case.
    bracket = pb.generate_double_elim(make_participants(14), bye_rounds=_CUSTOM_14)
    assert not any(m.status is MatchStatus.BYE for m in bracket.matches)
    lb_rounds = sorted(
        {m.round_number for m in bracket.matches if m.bracket_side is BracketSide.LOSERS}
    )
    assert lb_rounds[0] == 1
    assert pb.get_winner(simulate(bracket)).id == 1


def test_standard_nonpoweroftwo_byes_also_collapse() -> None:
    # Collapse applies to ordinary non-power-of-two fields too, not just custom byes.
    bracket = pb.generate_double_elim(make_participants(6))
    assert not any(m.status is MatchStatus.BYE for m in bracket.matches)
    assert pb.get_winner(simulate(bracket)).id == 1


# --- compact-vs-padded equivalence (permanent guard: the two must never diverge) -----------
#
# `compact=False` keeps the original power-of-two padded structure; `compact=True` (default)
# collapses its pass-through byes. The compact form must play *identically* to the padded one —
# same matchups, same champion — for every supported field/bye configuration and any way the
# games fall. These tests pin that equivalence so the compactness step can never silently change
# who plays whom or who wins.

# Winner-pickers that depend only on *which seeds* meet (not match id or order), so the padded
# and compact brackets make identical choices for the same matchup however the rounds are laid out.
_STRATEGIES: dict[str, Callable[[int, int], int]] = {
    "chalk": lambda a, b: min(a, b),  # every favourite wins
    "all_upsets": lambda a, b: max(a, b),  # every underdog wins (stresses the losers bracket)
    "mixed": lambda a, b: a if ((a * 31 + b * 17) % 2 == 0) else b,  # deterministic mix
}


def _play(bracket: pb.Bracket, decide: Callable[[int, int], int]) -> pb.Bracket:
    guard = 0
    while not pb.is_complete(bracket):
        guard += 1
        assert guard < 2000, "simulation did not terminate"
        ready = pb.get_ready_matches(bracket)
        assert ready, "no ready matches but bracket is not complete"
        m = ready[0]
        bracket = pb.report_result(bracket, m.id, decide(m.participant1_id, m.participant2_id))
    return bracket


def _signature(bracket: pb.Bracket) -> tuple[Counter[frozenset[int]], int]:
    """The competitive content of a finished bracket, independent of match ids/structure:
    the multiset of who-played-whom plus the champion."""
    pairs: Counter[frozenset[int]] = Counter(
        frozenset((m.participant1_id, m.participant2_id))
        for m in bracket.matches
        if m.status is MatchStatus.COMPLETED
    )
    return pairs, pb.get_winner(bracket).id


def _all_bye_configs() -> list[tuple[int, dict[int, int]]]:
    cases: list[tuple[int, dict[int, int]]] = []
    for n in range(4, 25):
        for option in pb.allowable_bye_options(n, max_bye_level=MAX_DOUBLE_ELIM_BYE_LEVEL):
            requested = {s: v for s, v in option.to_bye_rounds().items() if v > 0}
            try:
                pb.complete_bye_rounds(n, requested)
            except pb.ValidationError:
                continue
            cases.append((n, requested))
    return cases


_BYE_PARAMS = [
    pytest.param(n, req, id=f"n{n}-" + "_".join(f"{s}x{v}" for s, v in sorted(req.items())))
    for n, req in _all_bye_configs()
]
_STANDARD_NS = [3, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 17, 20, 24]


@pytest.mark.parametrize("strategy", list(_STRATEGIES))
@pytest.mark.parametrize("n, bye_rounds", _BYE_PARAMS)
def test_compact_plays_identically_to_padded_custom_byes(
    n: int, bye_rounds: dict[int, int], strategy: str
) -> None:
    decide = _STRATEGIES[strategy]
    padded = pb.generate_double_elim(make_participants(n), bye_rounds=bye_rounds, compact=False)
    compact = pb.generate_double_elim(make_participants(n), bye_rounds=bye_rounds, compact=True)
    assert not any(m.status is MatchStatus.BYE for m in compact.matches)
    assert _signature(_play(padded, decide)) == _signature(_play(compact, decide))


@pytest.mark.parametrize("strategy", list(_STRATEGIES))
@pytest.mark.parametrize("n", _STANDARD_NS)
def test_compact_plays_identically_to_padded_standard(n: int, strategy: str) -> None:
    # The default (no bye_rounds) path: ordinary non-power-of-two fields must match too.
    decide = _STRATEGIES[strategy]
    padded = pb.generate_double_elim(make_participants(n), compact=False)
    compact = pb.generate_double_elim(make_participants(n), compact=True)
    assert not any(m.status is MatchStatus.BYE for m in compact.matches)
    assert _signature(_play(padded, decide)) == _signature(_play(compact, decide))


@pytest.mark.parametrize("n, bye_rounds", _BYE_PARAMS)
def test_compact_keeps_exactly_the_real_matches(n: int, bye_rounds: dict[int, int]) -> None:
    # The compact bracket has exactly the padded bracket's *real* matches — those that will host a
    # two-player contest (occupant count 2), plus the grand-final reset. (Counting by status would
    # be wrong: an empty losers bye match starts 'pending', only flipping to 'bye' once filled.)
    padded = pb.generate_double_elim(make_participants(n), bye_rounds=bye_rounds, compact=False)
    compact = pb.generate_double_elim(make_participants(n), bye_rounds=bye_rounds, compact=True)
    counts = compute_occupant_counts(padded)
    kept_in_padded = sum(
        1
        for m in padded.matches
        if counts[m.id] == 2
        or (m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2)
    )
    assert kept_in_padded == len(compact.matches)
    assert not pb.is_complete(compact)


def test_compact_param_default_is_true() -> None:
    byed = pb.generate_double_elim(make_participants(6))
    assert not any(m.status is MatchStatus.BYE for m in byed.matches)


def test_collapse_unwind_roundtrips() -> None:
    bracket = pb.generate_double_elim(make_participants(14), bye_rounds=_CUSTOM_14)
    first = pb.get_ready_matches(bracket)[0]
    winner = first.participant1_id
    advanced = pb.report_result(bracket, first.id, winner)
    assert pb.get_match(advanced, first.id).status is MatchStatus.COMPLETED
    reverted, _ = pb.unwind_result(advanced, first.id)
    assert pb.get_match(reverted, first.id).status is MatchStatus.READY
    assert pb.get_match(reverted, first.id).winner_id is None
