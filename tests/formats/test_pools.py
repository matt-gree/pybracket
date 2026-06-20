"""Pools as a phase: a grouped round-robin phase feeding an elimination phase.

This is the decomposition of the old ``PoolsBracket`` — `Phase(format="round_robin",
groups=N)` into `Phase(format=<elim>, entrants=Qualification(top_of_each_group(...)))`. These
tests preserve the original pools coverage (snake assignment, rematch avoidance, draft/publish,
preview) on the generalized ``Tournament`` engine.
"""

from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import (
    BracketState,
    PhaseSpec,
    Qualification,
    advance_phase,
    draft_phase,
    generate_tournament,
    phase_results,
    preview_phase,
    publish_phase,
    top_of_each_group,
)
from pybracket.models.tournament import Tournament

from tests.helpers import make_participants, simulate


def _pools_to_bracket(
    n: int,
    num_pools: int,
    advancement: int,
    bracket_format: str = "double_elim",
    seeding: str = "snake",
) -> Tournament:
    return generate_tournament(
        make_participants(n),
        phases=[
            PhaseSpec("pools", "round_robin", groups=num_pools),
            PhaseSpec(
                "cut",
                bracket_format,
                entrants=Qualification(
                    sources=top_of_each_group("pools", advancement), seeding=seeding
                ),
            ),
        ],
    )


def _play_pools(t: Tournament) -> Tournament:
    for i, bracket in enumerate(t.phases[0].brackets):
        t.phases[0].brackets[i] = simulate(bracket)
    return t


def _advancer_ids(t: Tournament, num_pools: int, advancement: int) -> list[int]:
    out: list[int] = []
    for g in range(num_pools):
        out.extend(r.participant_id for r in phase_results(t, "pools", g)[:advancement])
    return out


def test_snake_assignment_sizes() -> None:
    t = _pools_to_bracket(8, num_pools=2, advancement=2)
    pools = t.phases[0].brackets
    assert [len(p.participants) for p in pools] == [4, 4]
    # Snake: seeds 1,4,5,8 -> pool A; 2,3,6,7 -> pool B.
    assert {p.seed for p in pools[0].participants} == {1, 4, 5, 8}


def test_uneven_pools_extras_to_earliest() -> None:
    t = _pools_to_bracket(10, num_pools=4, advancement=2)
    assert [len(p.participants) for p in t.phases[0].brackets] == [3, 3, 2, 2]


def test_cut_starts_empty_draft() -> None:
    t = _pools_to_bracket(8, num_pools=2, advancement=2)
    assert t.phases[1].state is BracketState.DRAFT
    assert t.phases[1].brackets == []


def test_draft_requires_complete_pools() -> None:
    t = _pools_to_bracket(8, num_pools=2, advancement=2)
    with pytest.raises(pb.BracketStateError):
        draft_phase(t, "cut")


def test_full_pools_to_double_elim() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2, bracket_format="double_elim"))
    t = advance_phase(t, "cut")
    cut = t.phases[1].brackets[0]
    assert cut.state is BracketState.PUBLISHED
    assert cut.format == "double_elim"
    assert len(cut.participants) == 4  # 2 pools * 2 advancing
    t.phases[1].brackets[0] = simulate(cut)
    assert pb.is_complete(t.phases[1].brackets[0])


def test_full_pools_to_single_elim() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2, bracket_format="single_elim"))
    t = advance_phase(t, "cut")
    assert t.phases[1].brackets[0].format == "single_elim"
    t.phases[1].brackets[0] = simulate(t.phases[1].brackets[0])
    assert pb.get_winner(t.phases[1].brackets[0]) is not None


def test_rematch_avoidance_no_same_pool_round_one() -> None:
    t = _pools_to_bracket(16, num_pools=4, advancement=2, bracket_format="single_elim")
    pool_of = {
        p.id: i for i, pool in enumerate(t.phases[0].brackets) for p in pool.participants
    }
    t = _play_pools(t)
    t = draft_phase(t, "cut")
    for m in t.phases[1].brackets[0].matches:
        if m.round_number == 1 and m.participant1_id is not None and m.participant2_id is not None:
            assert pool_of[m.participant1_id] != pool_of[m.participant2_id]


def test_manual_seed_override() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2))
    advancers = _advancer_ids(t, num_pools=2, advancement=2)
    t = draft_phase(t, "cut", new_seed_order=advancers)
    assert len(t.phases[1].brackets[0].participants) == 4


def test_groups_must_be_positive() -> None:
    with pytest.raises(pb.ValidationError):
        generate_tournament(
            make_participants(8),
            phases=[PhaseSpec("pools", "round_robin", groups=0)],
        )


def test_advancement_cannot_exceed_pool_size() -> None:
    # 8 players over 2 pools = 4 each; advancing 5 is impossible.
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=5))
    with pytest.raises(pb.ValidationError):
        draft_phase(t, "cut")


# --- DRAFT -> publish flow ----------------------------------------------------------------


def test_draft_produces_draft_bracket() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2))
    t = draft_phase(t, "cut")
    cut = t.phases[1].brackets[0]
    assert cut.state is BracketState.DRAFT
    assert len(cut.matches) > 0
    assert len(cut.participants) == 4


def test_publish_transitions_draft_to_published() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2))
    t = publish_phase(draft_phase(t, "cut"), "cut")
    cut = t.phases[1].brackets[0]
    assert cut.state is BracketState.PUBLISHED
    t.phases[1].brackets[0] = simulate(cut)
    assert pb.is_complete(t.phases[1].brackets[0])


def test_publish_rejects_non_draft_bracket() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2))
    t = advance_phase(t, "cut")  # already PUBLISHED
    with pytest.raises(pb.BracketStateError):
        publish_phase(t, "cut")


def test_advance_phase_is_draft_then_publish() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2))
    one_step = advance_phase(t, "cut")
    two_step = publish_phase(draft_phase(t, "cut"), "cut")
    assert pb.bracket_to_dict(one_step.phases[1].brackets[0]) == pb.bracket_to_dict(
        two_step.phases[1].brackets[0]
    )


def test_draft_reorder_changes_seeding_before_publish() -> None:
    t = _play_pools(_pools_to_bracket(8, num_pools=2, advancement=2))
    advancers = _advancer_ids(t, num_pools=2, advancement=2)

    default = draft_phase(t, "cut")
    first_default = [m for m in default.phases[1].brackets[0].matches if m.round_number == 1][0]

    reordered = draft_phase(t, "cut", new_seed_order=list(reversed(advancers)))
    first_reordered = [
        m for m in reordered.phases[1].brackets[0].matches if m.round_number == 1
    ][0]
    assert (first_default.participant1_id, first_default.participant2_id) != (
        first_reordered.participant1_id,
        first_reordered.participant2_id,
    )


# --- preview (preliminary bracket before pools finish) ------------------------------------


def test_preview_before_pools_complete() -> None:
    t = _pools_to_bracket(12, num_pools=3, advancement=2, bracket_format="single_elim")
    t = preview_phase(t, "cut")  # never requires the pools to be played
    cut = t.phases[1].brackets[0]
    assert cut.config["preview"] is True
    assert cut.state is BracketState.DRAFT
    assert len(cut.participants) == 6  # 3 pools * 2 advancing
    assert all(p.id < 0 for p in cut.participants)
    assert all(p.stats.get("placeholder") for p in cut.participants)
    assert any("#1" in p.name for p in cut.participants)
    # The pools are carried over untouched.
    assert all(not pb.is_complete(p) for p in t.phases[0].brackets)


def test_preview_avoids_same_pool_round_one() -> None:
    t = _pools_to_bracket(16, num_pools=4, advancement=2, bracket_format="single_elim")
    t = preview_phase(t, "cut")
    cut = t.phases[1].brackets[0]
    origin = {p.id: p.stats["origin_group"] for p in cut.participants}
    for m in cut.matches:
        if m.round_number == 1 and m.participant1_id is not None and m.participant2_id is not None:
            assert origin[m.participant1_id] != origin[m.participant2_id]


def test_preview_double_elim_shape() -> None:
    t = _pools_to_bracket(8, num_pools=2, advancement=2, bracket_format="double_elim")
    t = preview_phase(t, "cut")
    cut = t.phases[1].brackets[0]
    assert cut.format == "double_elim"
    assert len(cut.participants) == 4


def test_preview_seeding_matches_real_draft_positions() -> None:
    """Each (group, place) origin lands in the same slot the real draft would place it."""
    t = _pools_to_bracket(12, num_pools=3, advancement=2, bracket_format="single_elim")
    preview = preview_phase(t, "cut")

    played = _play_pools(t)
    origin: dict[int, tuple[int, int]] = {}
    for g in range(3):
        for place, ranked in enumerate(phase_results(played, "pools", g)[:2], start=1):
            origin[ranked.participant_id] = (g, place)
    drafted = draft_phase(played, "cut")

    prev_origin = {
        p.id: (p.stats["origin_group"], p.stats["origin_place"])
        for p in preview.phases[1].brackets[0].participants
    }

    def pairs(bracket: pb.Bracket, lookup: dict[int, tuple[int, int]]) -> list[object]:
        out: list[object] = []
        for m in sorted(
            (m for m in bracket.matches if m.round_number == 1), key=lambda m: m.id
        ):
            out.append((lookup.get(m.participant1_id), lookup.get(m.participant2_id)))
        return out

    assert pairs(preview.phases[1].brackets[0], prev_origin) == pairs(
        drafted.phases[1].brackets[0], origin
    )
