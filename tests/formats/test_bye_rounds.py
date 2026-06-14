from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import MatchStatus

from tests.helpers import make_participants, simulate


def _first_round_of(bracket: pb.Bracket, participant_id: int) -> int:
    """The round number of a participant's first match (where it is initially placed)."""
    rounds = [
        m.round_number
        for m in bracket.matches
        if participant_id in (m.participant1_id, m.participant2_id)
    ]
    return min(rounds)


# --- structure -----------------------------------------------------------------------------


def test_bye_rounds_none_is_classic_behaviour() -> None:
    # Without bye_rounds, a 5-player field still rounds up to 8 with single-round byes.
    bracket = pb.generate_single_elim(make_participants(5))
    assert "bye_rounds" not in bracket.config
    assert any(m.status is MatchStatus.BYE for m in bracket.matches)


def test_empty_bye_rounds_builds_standard_power_of_two() -> None:
    bracket = pb.generate_single_elim(make_participants(8), bye_rounds={})
    assert len(bracket.matches) == 7
    assert len(bracket.rounds) == 3
    # A clean power-of-two field needs no byes at all.
    assert all(m.status is not MatchStatus.BYE for m in bracket.matches)
    bracket = simulate(bracket)
    assert pb.get_winner(bracket).id == 1


def test_seed_enters_at_round_equal_to_byes_plus_one() -> None:
    bye = {1: 2, 2: 2, 3: 1, 4: 1}  # N=8: seeds 1-2 double bye, seeds 3-4 single bye
    bracket = pb.generate_single_elim(make_participants(8), bye_rounds=bye)
    assert _first_round_of(bracket, 1) == 3  # 2 byes -> first match in round 3
    assert _first_round_of(bracket, 3) == 2  # 1 bye  -> round 2
    assert _first_round_of(bracket, 5) == 1  # 0 byes -> round 1


@pytest.mark.parametrize(
    "n,bye",
    [
        (8, {1: 2, 2: 2, 3: 1, 4: 1}),
        (16, {**dict.fromkeys(range(1, 5), 2), **dict.fromkeys(range(5, 9), 1)}),
        (5, {1: 3, 2: 2, 3: 1}),
    ],
)
def test_total_match_count_is_n_minus_one(n: int, bye: dict[int, int]) -> None:
    # Every match has two real participants and eliminates exactly one player, so a valid
    # bye configuration produces exactly N - 1 matches (no empty/phantom bye matches).
    bracket = pb.generate_single_elim(make_participants(n), bye_rounds=bye)
    real = [m for m in bracket.matches if not m.metadata.get("consolation")]
    assert len(real) == n - 1
    assert all(m.status is not MatchStatus.BYE for m in bracket.matches)


def test_bye_rounds_stored_as_full_per_seed_map() -> None:
    bracket = pb.generate_single_elim(make_participants(4), bye_rounds={1: 2, 2: 1})
    assert bracket.config["bye_rounds"] == {1: 2, 2: 1, 3: 0, 4: 0}


# --- seeding & layout ----------------------------------------------------------------------


def _winner_feeders(bracket: pb.Bracket, match_id: int) -> list[int]:
    return [m.id for m in bracket.matches if m.next_winner_match_id == match_id]


def _seed_first_match(bracket: pb.Bracket, seed: int) -> int:
    participant = next(p.id for p in bracket.participants if p.seed == seed)
    return min(
        m.id
        for m in bracket.matches
        if participant in (m.participant1_id, m.participant2_id)
    )


def _ancestor_at_round(bracket: pb.Bracket, match_id: int, target_round: int) -> int:
    """Walk winner pointers up from a match until reaching the match in ``target_round``."""
    by_id = {m.id: m for m in bracket.matches}
    current = match_id
    while by_id[current].round_number < target_round:
        nxt = by_id[current].next_winner_match_id
        assert nxt is not None
        current = nxt
    return current


def test_double_byes_respect_seeding_opposite_halves() -> None:
    # 16-field, top 4 double byes + 4 single byes. Seeds 1 & 2 must be in opposite halves
    # (meet only in the final); the semifinals must pair (1 vs 4) and (2 vs 3).
    bracket = pb.generate_single_elim(
        make_participants(16), bye_rounds={1: 2, 2: 2, 3: 2, 4: 2}
    )
    final = next(m.id for m in bracket.matches if m.next_winner_match_id is None)
    semis = _winner_feeders(bracket, final)
    assert len(semis) == 2
    semi_of = {
        seed: _ancestor_at_round(bracket, _seed_first_match(bracket, seed), 4)
        for seed in (1, 2, 3, 4)
    }
    # 1 with 4, 2 with 3; the two pairs are the two different semifinals.
    assert semi_of[1] == semi_of[4]
    assert semi_of[2] == semi_of[3]
    assert semi_of[1] != semi_of[2]
    assert {semi_of[1], semi_of[2]} == set(semis)


def _winner_subtree(bracket: pb.Bracket, root_id: int) -> list[int]:
    feeders: dict[int, list[int]] = {}
    for m in bracket.matches:
        if m.next_winner_match_id is not None:
            feeders.setdefault(m.next_winner_match_id, []).append(m.id)
    out: list[int] = []
    stack = [root_id]
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(feeders.get(node, []))
    return out


@pytest.mark.parametrize(
    "n,bye",
    [
        (16, {1: 2, 2: 2, 3: 2, 4: 2}),
        (8, {1: 2, 2: 2, 3: 1, 4: 1}),
        (14, {1: 2, 2: 2, 3: 2, 4: 2}),
        (16, {**dict.fromkeys(range(1, 5), 2), **dict.fromkeys(range(5, 9), 1)}),
    ],
)
def test_round_ordering_is_render_ready(n: int, bye: dict[int, int]) -> None:
    # Left-first ids make every winner-subtree a contiguous id range ending at its root, so a
    # tree layout draws the bracket without sibling subtrees interleaving (no crossed lines).
    bracket = pb.generate_single_elim(make_participants(n), bye_rounds=bye)
    for m in bracket.matches:
        if m.metadata.get("consolation"):
            continue
        subtree = sorted(_winner_subtree(bracket, m.id))
        assert subtree == list(range(subtree[0], m.id + 1))


# --- the gauntlet continuum ----------------------------------------------------------------


@pytest.mark.parametrize("n", [4, 5, 6, 8])
def test_gauntlet_bye_config_reproduces_single_gauntlet(n: int) -> None:
    # A gauntlet is the degenerate single-elim where each higher seed gets exactly one more
    # bye than the next: seed k enters at round (n - k), i.e. byes = n - k - 1.
    bye = {k: n - k - 1 for k in range(1, n - 1)}
    bracket = pb.generate_single_elim(make_participants(n), bye_rounds=bye)
    chain = pb.generate_gauntlet(make_participants(n), style="single")
    assert len(bracket.matches) == len(chain.matches) == n - 1
    # Linear chain: every round has exactly one match.
    assert all(len(r.match_ids) == 1 for r in bracket.rounds)
    bracket = simulate(bracket)
    assert pb.get_winner(bracket).id == 1


# --- simulation / favourites ---------------------------------------------------------------


@pytest.mark.parametrize(
    "n,bye",
    [
        (8, {1: 2, 2: 2, 3: 1, 4: 1}),
        (16, {**dict.fromkeys(range(1, 5), 2), **dict.fromkeys(range(5, 9), 1)}),
        (4, {1: 2, 2: 1}),
    ],
)
def test_favourites_win_yields_top_seed_champion(n: int, bye: dict[int, int]) -> None:
    bracket = pb.generate_single_elim(make_participants(n), bye_rounds=bye)
    bracket = simulate(bracket)
    assert pb.is_complete(bracket)
    assert pb.get_winner(bracket).id == 1


# --- third place ---------------------------------------------------------------------------


def test_third_place_with_byes_when_final_has_two_feeders() -> None:
    bye = {1: 2, 2: 2, 3: 1, 4: 1}  # N=8 -> final fed by two semifinals
    bracket = pb.generate_single_elim(
        make_participants(8), bye_rounds=bye, third_place_match=True
    )
    assert len([m for m in bracket.matches if m.metadata.get("consolation")]) == 1
    bracket = simulate(bracket)
    placements = {p.participant_id: p for p in pb.get_placements(bracket)}
    assert placements[3].position == 3


def test_third_place_rejected_when_final_has_single_feeder() -> None:
    # A gauntlet config: seed 1 enters directly into the final, so there is no pair of
    # semifinal losers to contest third place.
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(
            make_participants(4), bye_rounds={1: 2, 2: 1}, third_place_match=True
        )


# --- validation ----------------------------------------------------------------------------


def test_incomplete_byes_are_auto_completed() -> None:
    # A request that does not tile a clean bracket is completed by adding the minimal extra
    # byes, rather than rejected: {1:2, 2:1, 3:1} for N=8 needs single byes for seeds 4-6.
    bracket = pb.generate_single_elim(make_participants(8), bye_rounds={1: 2, 2: 1, 3: 1})
    assert bracket.config["bye_rounds"] == {1: 2, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 0, 8: 0}
    assert bracket.config["bye_rounds_added"] == {4: 1, 5: 1, 6: 1}
    assert bracket.config["bye_rounds_requested"] == {1: 2, 2: 1, 3: 1}
    real = [m for m in bracket.matches if not m.metadata.get("consolation")]
    assert len(real) == 7  # N - 1, no phantom byes
    bracket = simulate(bracket)
    assert pb.get_winner(bracket).id == 1


def test_top_seeds_double_bye_auto_completes_with_single_byes() -> None:
    # The headline case: the TO asks only for the top four to get double byes; the engine fills
    # in the single byes (seeds 5-8) needed to make a 16-field tile a bracket.
    bracket = pb.generate_single_elim(
        make_participants(16), bye_rounds={1: 2, 2: 2, 3: 2, 4: 2}
    )
    assert bracket.config["bye_rounds_added"] == {5: 1, 6: 1, 7: 1, 8: 1}


def test_overspecified_byes_rejected() -> None:
    # Byes that cannot be honoured by the field (round 1 would be empty) are rejected.
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(4), bye_rounds={1: 3})


def test_negative_byes_rejected() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(4), bye_rounds={1: -1})


def test_non_integer_byes_rejected() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(4), bye_rounds={1: 1.5})  # type: ignore[dict-item]


def test_boolean_byes_rejected() -> None:
    # bool is a subclass of int; reject it explicitly to avoid silent surprises.
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(4), bye_rounds={1: True})  # type: ignore[dict-item]


def test_non_monotonic_byes_rejected() -> None:
    # A worse seed cannot receive more byes than a better one.
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(4), bye_rounds={1: 1, 2: 2})


def test_unknown_seed_rejected() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(4), bye_rounds={9: 1})


def test_protected_seeds_and_bye_rounds_cannot_combine() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(
            make_participants(8), protected_seeds=4, bye_rounds={1: 2, 2: 1}
        )


def test_too_many_byes_for_field_rejected() -> None:
    # Seed 1 cannot skip more rounds than the bracket has.
    with pytest.raises(pb.ValidationError):
        pb.generate_single_elim(make_participants(3), bye_rounds={1: 5})


# --- serialization / reseed ----------------------------------------------------------------


def test_bye_rounds_survives_dict_and_json_round_trip() -> None:
    bracket = pb.generate_single_elim(make_participants(5), bye_rounds={1: 3, 2: 2, 3: 1})
    via_dict = pb.bracket_from_dict(pb.bracket_to_dict(bracket))
    via_json = pb.bracket_from_json(pb.bracket_to_json(bracket))
    assert via_dict == bracket
    assert via_json == bracket
    # Keys stay integers even through JSON (which stringifies them).
    assert all(isinstance(k, int) for k in via_json.config["bye_rounds"])


def test_reseed_preserves_bye_rounds() -> None:
    bracket = pb.generate_single_elim(make_participants(5), bye_rounds={1: 3, 2: 2, 3: 1})
    reseeded = pb.reseed(bracket, [5, 4, 3, 2, 1])
    assert reseeded.config["bye_rounds"] == {1: 3, 2: 2, 3: 1, 4: 0, 5: 0}
    assert len(reseeded.matches) == len(bracket.matches)
    # The new seed 1 (originally participant 5) now receives the double-plus byes and wins.
    reseeded = simulate(reseeded)
    assert pb.get_winner(reseeded).id == 5
