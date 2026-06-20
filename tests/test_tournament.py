from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import (
    BracketStateError,
    PhaseSpec,
    Qualification,
    ValidationError,
    advance_phase,
    all_of,
    dependent_phases,
    draft_phase,
    edit_changes_advancement,
    edit_phase_result,
    generate_tournament,
    is_phase_draftable,
    phase_is_complete,
    phase_results,
    place,
    places,
    preview_phase,
    publish_phase,
    revert_phase,
    top,
    top_of_each_group,
    tournament_from_dict,
    tournament_from_json,
    tournament_to_dict,
    tournament_to_json,
    unwind_phase_result,
)
from pybracket.models.tournament import Tournament

from tests.helpers import make_participants, simulate


def _play_phase(t: Tournament, phase_id: str) -> None:
    """Play every sub-bracket of a phase to completion, in place."""
    phase = next(p for p in t.phases if p.id == phase_id)
    swiss = phase.format == "swiss"
    for i, bracket in enumerate(phase.brackets):
        phase.brackets[i] = simulate(bracket, advance_swiss=swiss)


def _match_between(bracket: object, a: int, b: int) -> int:
    for m in bracket.matches:  # type: ignore[attr-defined]
        if {m.participant1_id, m.participant2_id} == {a, b}:
            return int(m.id)
    raise AssertionError(f"no match between {a} and {b}")


def _pools_cut() -> Tournament:
    """8 players, 2 pools of 4 (pool A = seeds 1,4,5,8), top 2 advance; pools played, cut live."""
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    _play_phase(t, "pools")
    return advance_phase(t, "cut")


# --------------------------------------------------------------------------------------
# Pools -> bracket (the decomposed PoolsBracket)
# --------------------------------------------------------------------------------------


def test_pools_to_bracket_end_to_end() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec(
                "cut",
                "single_elim",
                entrants=Qualification(sources=top_of_each_group("pools", 2)),
            ),
        ],
    )
    assert len(t.phases[0].brackets) == 2
    assert [len(b.participants) for b in t.phases[0].brackets] == [4, 4]
    assert not is_phase_draftable(t, "cut")

    _play_phase(t, "pools")
    assert phase_is_complete(t.phases[0])
    assert is_phase_draftable(t, "cut")

    t = draft_phase(t, "cut")
    assert t.phases[1].state is pb.BracketState.DRAFT
    assert len(t.phases[1].brackets[0].participants) == 4

    t = publish_phase(t, "cut")
    assert t.phases[1].state is pb.BracketState.PUBLISHED
    _play_phase(t, "cut")
    champ = pb.get_winner(t.phases[1].brackets[0])
    assert champ is not None and champ.id == 1


def test_advance_phase_is_draft_plus_publish() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "double_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    _play_phase(t, "pools")
    t = advance_phase(t, "cut")
    assert t.phases[1].state is pb.BracketState.PUBLISHED
    _play_phase(t, "cut")
    assert phase_is_complete(t.phases[1])


# --------------------------------------------------------------------------------------
# High / low pools -> top cut  (Slice 2024 "Stars Off")
# --------------------------------------------------------------------------------------


def test_high_low_merge_ragged_sources() -> None:
    # High pool (group 0): everyone advances (seed-only). Low pool (group 1): top 2 only.
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec(
                "cut",
                "single_elim",
                entrants=Qualification(
                    sources=all_of("pools#0") + top("pools#1", 2),
                    seeding="snake",
                ),
            ),
        ],
    )
    _play_phase(t, "pools")
    t = draft_phase(t, "cut")
    # 4 (high) + 2 (low) = 6 entrants.
    assert len(t.phases[1].brackets[0].participants) == 6
    t = publish_phase(t, "cut")
    _play_phase(t, "cut")
    assert phase_is_complete(t.phases[1])


# --------------------------------------------------------------------------------------
# Swiss -> top cut
# --------------------------------------------------------------------------------------


def test_swiss_to_top_cut() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("swiss", "swiss", config={"rounds": 3}),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top("swiss", 4), seeding="rank")),
        ],
    )
    _play_phase(t, "swiss")
    assert phase_is_complete(t.phases[0])
    t = advance_phase(t, "cut")
    assert len(t.phases[1].brackets[0].participants) == 4
    _play_phase(t, "cut")
    assert phase_is_complete(t.phases[1])


# --------------------------------------------------------------------------------------
# Three stages: pools -> pools -> bracket
# --------------------------------------------------------------------------------------


def test_three_stage_pools_pools_bracket() -> None:
    t = generate_tournament(
        make_participants(16),
        phases=[
            PhaseSpec("r1", "round_robin", groups=4),
            PhaseSpec("r2", "round_robin", groups=2,
                      entrants=Qualification(sources=top_of_each_group("r1", 2))),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("r2", 2))),
        ],
    )
    assert [len(b.participants) for b in t.phases[0].brackets] == [4, 4, 4, 4]
    _play_phase(t, "r1")
    t = advance_phase(t, "r2")          # 4 groups * top 2 = 8, into 2 pools of 4
    assert [len(b.participants) for b in t.phases[1].brackets] == [4, 4]
    _play_phase(t, "r2")
    t = advance_phase(t, "cut")         # 2 groups * top 2 = 4
    assert len(t.phases[2].brackets[0].participants) == 4
    _play_phase(t, "cut")
    assert phase_is_complete(t.phases[2])


# --------------------------------------------------------------------------------------
# groups is orthogonal to format: bracket-shaped pools
# --------------------------------------------------------------------------------------


def test_grouped_elimination_phase() -> None:
    # 4 parallel single-elim brackets as one phase; the winner of each advances.
    t = generate_tournament(
        make_participants(16),
        phases=[
            PhaseSpec("waves", "single_elim", groups=4),
            PhaseSpec("final", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("waves", 1))),
        ],
    )
    assert len(t.phases[0].brackets) == 4
    assert all(b.format == "single_elim" for b in t.phases[0].brackets)
    _play_phase(t, "waves")
    t = advance_phase(t, "final")
    assert len(t.phases[1].brackets[0].participants) == 4
    _play_phase(t, "final")
    assert phase_is_complete(t.phases[1])


# --------------------------------------------------------------------------------------
# Truncation: a qualifying bracket that stops at top-N and hands off to a final
# --------------------------------------------------------------------------------------


def test_qualifier_bracket_to_final() -> None:
    t = generate_tournament(
        make_participants(16),
        phases=[
            PhaseSpec("qual", "single_elim", config={"survivors": 8}),
            PhaseSpec("final", "double_elim",
                      entrants=Qualification(sources=top("qual", 8), seeding="rank")),
        ],
    )
    assert [r.name for r in t.phases[0].brackets[0].rounds] == ["Round 1"]
    _play_phase(t, "qual")
    assert phase_is_complete(t.phases[0])
    # Exactly the 8 survivors advance.
    survivors = [r.participant_id for r in phase_results(t, "qual")[:8]]
    t = advance_phase(t, "final")
    assert len(t.phases[1].brackets[0].participants) == 8
    assert {p.id for p in t.phases[1].brackets[0].participants} == set(survivors)
    _play_phase(t, "final")
    assert pb.get_winner(t.phases[1].brackets[0]) is not None


# --------------------------------------------------------------------------------------
# Seeding override, preview, revert
# --------------------------------------------------------------------------------------


def test_manual_seed_order_override() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    _play_phase(t, "pools")
    qualifiers = [r.participant_id for r in phase_results(t, "pools", 0)][:2]
    qualifiers += [r.participant_id for r in phase_results(t, "pools", 1)][:2]
    reversed_order = list(reversed(qualifiers))
    t = draft_phase(t, "cut", new_seed_order=reversed_order)
    seeds = sorted(t.phases[1].brackets[0].participants, key=lambda p: p.seed)
    assert [p.id for p in seeds] == reversed_order


def test_preview_then_real_draft() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    t = preview_phase(t, "cut")  # before pools are played
    assert all(b.config.get("preview") for b in t.phases[1].brackets)
    names = {p.name for p in t.phases[1].brackets[0].participants}
    assert any("#1" in n for n in names)  # placeholders naming pool finishes
    with pytest.raises(BracketStateError):
        publish_phase(t, "cut")  # cannot publish a preview

    _play_phase(t, "pools")
    t = draft_phase(t, "cut")
    assert not any(b.config.get("preview") for b in t.phases[1].brackets)
    assert all(p.id > 0 for p in t.phases[1].brackets[0].participants)


def test_revert_phase_tears_down() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    _play_phase(t, "pools")
    t = advance_phase(t, "cut")
    t = revert_phase(t, "cut")
    assert t.phases[1].brackets == []
    assert t.phases[1].state is pb.BracketState.DRAFT
    assert is_phase_draftable(t, "cut")  # sources still complete -> can re-draft


# --------------------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------------------


def test_serialization_round_trip() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "double_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2),
                                             seeding="snake")),
        ],
    )
    _play_phase(t, "pools")
    t = advance_phase(t, "cut")

    via_dict = tournament_from_dict(tournament_to_dict(t))
    via_json = tournament_from_json(tournament_to_json(t))
    for restored in (via_dict, via_json):
        assert len(restored.phases) == 2
        assert restored.phases[1].entrants is not None
        assert restored.phases[1].entrants.seeding == "snake"
        assert restored.phases[1].entrants.sources[0].phase == "pools"
        assert [len(b.participants) for b in restored.phases[0].brackets] == [4, 4]
        assert restored.phases[1].brackets[0].format == "double_elim"


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_unknown_phase_reference_rejected() -> None:
    with pytest.raises(ValidationError):
        generate_tournament(
            make_participants(8),
            phases=[
                PhaseSpec("pools", "round_robin", groups=2),
                PhaseSpec("cut", "single_elim",
                          entrants=Qualification(sources=top("nope", 4))),
            ],
        )


def test_forward_reference_rejected() -> None:
    with pytest.raises(ValidationError):
        generate_tournament(
            make_participants(8),
            phases=[
                PhaseSpec("cut", "single_elim",
                          entrants=Qualification(sources=top("pools", 4))),
                PhaseSpec("pools", "round_robin", groups=2),
            ],
        )


def test_duplicate_phase_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        generate_tournament(
            make_participants(8),
            phases=[
                PhaseSpec("x", "round_robin", groups=2),
                PhaseSpec("x", "single_elim",
                          entrants=Qualification(sources=top("x", 2))),
            ],
        )


def test_second_phase_without_entrants_rejected() -> None:
    with pytest.raises(ValidationError):
        generate_tournament(
            make_participants(8),
            phases=[
                PhaseSpec("a", "round_robin", groups=2),
                PhaseSpec("b", "round_robin", groups=2),  # no entrants, not first
            ],
        )


def test_draft_before_sources_complete_rejected() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    with pytest.raises(BracketStateError):
        draft_phase(t, "cut")


def test_place_exceeding_group_size_rejected() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),  # 4 per pool
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=places("pools#0", 1, 9))),
        ],
    )
    _play_phase(t, "pools")
    with pytest.raises(ValidationError):
        draft_phase(t, "cut")


# --------------------------------------------------------------------------------------
# Cross-phase edit / unwind gate (§11)
# --------------------------------------------------------------------------------------


def test_dependent_phases_helper() -> None:
    t = generate_tournament(
        make_participants(16),
        phases=[
            PhaseSpec("r1", "round_robin", groups=4),
            PhaseSpec("r2", "round_robin", groups=2,
                      entrants=Qualification(sources=top_of_each_group("r1", 2))),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("r2", 2))),
        ],
    )
    assert dependent_phases(t, "r1") == ["r2"]
    assert dependent_phases(t, "r1", transitive=True) == ["r2", "cut"]
    assert dependent_phases(t, "cut") == []


def test_edit_neutral_to_advancement_keeps_dependents() -> None:
    # Flipping a match between two non-qualifiers (pool A seeds 5 & 8) does not change top 2.
    t = _pools_cut()
    poolA = t.phases[0].brackets[0]
    match_id = _match_between(poolA, 5, 8)
    assert edit_changes_advancement(t, "pools", match_id, 8) == []

    edited = edit_phase_result(t, "pools", match_id, 8)
    assert edited.phases[1].brackets  # cut left intact
    # The pool result actually changed: 8 now ranks ahead of 5.
    order = [r.participant_id for r in phase_results(edited, "pools", 0)]
    assert order.index(8) < order.index(5)


def test_edit_changing_advancement_is_blocked() -> None:
    # Flipping pool A's 1-vs-4 match reorders the qualifiers (their seeds into the cut swap).
    t = _pools_cut()
    poolA = t.phases[0].brackets[0]
    match_id = _match_between(poolA, 1, 4)
    assert edit_changes_advancement(t, "pools", match_id, 4) == ["cut"]
    with pytest.raises(BracketStateError):
        edit_phase_result(t, "pools", match_id, 4)


def test_unwind_blocked_while_dependent_live() -> None:
    t = _pools_cut()
    match_id = _match_between(t.phases[0].brackets[0], 5, 8)
    with pytest.raises(BracketStateError):
        unwind_phase_result(t, "pools", match_id)


def test_revert_unblocks_edit_and_unwind() -> None:
    t = _pools_cut()
    poolA = t.phases[0].brackets[0]
    changing = _match_between(poolA, 1, 4)
    t = revert_phase(t, "cut")

    # Now no live dependent: the advancement-changing edit is allowed.
    assert edit_changes_advancement(t, "pools", changing, 4) == []
    t2 = edit_phase_result(t, "pools", changing, 4)
    assert phase_is_complete(t2.phases[0])

    # And a pure unwind is allowed, leaving the source incomplete.
    t3, signals = unwind_phase_result(t, "pools", changing)
    assert signals
    assert not phase_is_complete(t3.phases[0])


def test_edit_with_no_dependents_built_is_allowed() -> None:
    # Before the cut is drafted, editing pools is unguarded (nothing downstream is live).
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    _play_phase(t, "pools")
    match_id = _match_between(t.phases[0].brackets[0], 1, 4)
    assert edit_changes_advancement(t, "pools", match_id, 4) == []
    edit_phase_result(t, "pools", match_id, 4)  # does not raise


# --------------------------------------------------------------------------------------
# Non-elimination downstream phases draft in DRAFT, then publish (state= plumbing)
# --------------------------------------------------------------------------------------


def test_downstream_gauntlet_phase_drafts_draft_then_publishes() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("ladder", "gauntlet", config={"style": "dual"},
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    _play_phase(t, "pools")
    t = draft_phase(t, "ladder")
    assert t.phases[1].state is pb.BracketState.DRAFT
    assert t.phases[1].brackets[0].state is pb.BracketState.DRAFT
    t = publish_phase(t, "ladder")
    assert t.phases[1].brackets[0].state is pb.BracketState.PUBLISHED
    _play_phase(t, "ladder")
    assert pb.get_winner(t.phases[1].brackets[0]) is not None


# --------------------------------------------------------------------------------------
# Seeding policies, overall results, and edge / error paths
# --------------------------------------------------------------------------------------


def test_manual_seeding_preserves_source_order() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(
                          sources=top("pools#0", 2) + top("pools#1", 2),
                          seeding="manual")),
        ],
    )
    _play_phase(t, "pools")
    expected = (
        [r.participant_id for r in phase_results(t, "pools", 0)[:2]]
        + [r.participant_id for r in phase_results(t, "pools", 1)[:2]]
    )
    t = draft_phase(t, "cut")
    seeds = sorted(t.phases[1].brackets[0].participants, key=lambda p: p.seed)
    assert [p.id for p in seeds] == expected


def test_place_constructor_single_slots() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=[
                          place("pools#0", 1), place("pools#0", 2),
                          place("pools#1", 1), place("pools#1", 2),
                      ])),
        ],
    )
    _play_phase(t, "pools")
    t = draft_phase(t, "cut")
    assert len(t.phases[1].brackets[0].participants) == 4


def test_phase_results_overall_concatenates_groups() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[PhaseSpec("pools", "round_robin", groups=2)],
    )
    _play_phase(t, "pools")
    overall = phase_results(t, "pools")  # group=None
    assert len(overall) == 8
    assert {r.group for r in overall} == {0, 1}


def test_generate_tournament_requires_a_phase() -> None:
    with pytest.raises(ValidationError):
        generate_tournament(make_participants(8), phases=[])


def test_unsupported_format_rejected() -> None:
    with pytest.raises(ValidationError):
        generate_tournament(make_participants(8), phases=[PhaseSpec("x", "bogus")])


def test_field_phase_cannot_be_drafted_previewed_or_reverted() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("pools", 2))),
        ],
    )
    for op in (draft_phase, preview_phase, revert_phase):
        with pytest.raises(ValidationError):
            op(t, "pools")
    assert is_phase_draftable(t, "pools") is False


def test_unknown_phase_id_raises() -> None:
    t = generate_tournament(make_participants(8), phases=[PhaseSpec("pools", "round_robin", groups=2)])
    with pytest.raises(ValidationError):
        phase_results(t, "nope")


def test_preview_against_unbuilt_source_raises() -> None:
    t = generate_tournament(
        make_participants(16),
        phases=[
            PhaseSpec("r1", "round_robin", groups=4),
            PhaseSpec("r2", "round_robin", groups=2,
                      entrants=Qualification(sources=top_of_each_group("r1", 2))),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top_of_each_group("r2", 2))),
        ],
    )
    with pytest.raises(BracketStateError):
        preview_phase(t, "cut")  # r2 not built yet


def test_edit_group_out_of_range_rejected() -> None:
    t = _pools_cut()
    match_id = _match_between(t.phases[0].brackets[0], 5, 8)
    with pytest.raises(ValidationError):
        edit_phase_result(t, "pools", match_id, 8, group=5)


def test_unwind_group_out_of_range_rejected() -> None:
    t = _pools_cut()  # "cut" is terminal (no dependents)
    with pytest.raises(ValidationError):
        unwind_phase_result(t, "cut", 1, group=5)


def test_edit_that_decompletes_source_is_blocked() -> None:
    # Editing a semifinal in a completed single-elim cascades the final back to incomplete;
    # with a live dependent, that must be blocked.
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("main", "single_elim"),
            PhaseSpec("cons", "single_elim",
                      entrants=Qualification(sources=top("main", 2))),
        ],
    )
    _play_phase(t, "main")
    t = advance_phase(t, "cons")
    semi = next(m for m in t.phases[0].brackets[0].matches if m.round_number == 2)
    other = semi.participant2_id if semi.winner_id == semi.participant1_id else semi.participant1_id
    assert edit_changes_advancement(t, "main", semi.id, other) == ["cons"]
    with pytest.raises(BracketStateError):
        edit_phase_result(t, "main", semi.id, other)


def test_phase_resolving_to_too_few_entrants_rejected() -> None:
    t = generate_tournament(
        make_participants(8),
        phases=[
            PhaseSpec("pools", "round_robin", groups=2),
            PhaseSpec("cut", "single_elim",
                      entrants=Qualification(sources=top("pools#0", 1))),  # 1 entrant
        ],
    )
    _play_phase(t, "pools")
    with pytest.raises(ValidationError):
        draft_phase(t, "cut")
