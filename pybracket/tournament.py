"""Multi-stage tournaments: chain heterogeneous phases under one umbrella.

A :class:`Tournament` is an ordered list of :class:`Phase` objects. Phase 0 is seeded from the
participant field; every later phase draws its entrants from earlier phases through a
:class:`Qualification` of :class:`SlotRef` references. The boundary lifecycle
(draft -> preview -> publish) mirrors the old pools-to-bracket flow, generalized to any format
and any number of stages. See ``MULTISTAGE_DESIGN.md``.
"""

from __future__ import annotations

import copy
from typing import Any

from .advancement.engine import (
    UnwindSignal,
    is_complete,
    report_result,
    settle_initial,
    unwind_result,
)
from .advancement.placement import get_placements
from .errors import BracketStateError, ValidationError
from .formats.double_elim import build_double_elim
from .formats.gauntlet import generate_gauntlet
from .formats.round_robin import generate_round_robin
from .formats.single_elim import build_single_elim
from .formats.swiss import generate_swiss
from .models.bracket import Bracket
from .models.enums import AdvancementType, BracketState
from .models.participant import Participant
from .models.tournament import (
    ALL_PLACES,
    EACH_GROUP,
    Phase,
    PhaseSpec,
    Qualification,
    Ranked,
    SlotRef,
    Tournament,
)
from .seeding.algorithms import seed_slots
from .seeding.pool_seeding import (
    _repair_first_round as repair_first_round,
)
from .seeding.pool_seeding import (
    qualifier_seed_order,
    snake_pool_assignment,
)
from .tiebreakers.standings import get_standings
from .utils.math import next_power_of_2
from .utils.validation import validate_participants

__all__ = [
    "generate_tournament",
    "draft_phase",
    "preview_phase",
    "publish_phase",
    "revert_phase",
    "advance_phase",
    "phase_results",
    "phase_is_complete",
    "is_phase_draftable",
    "dependent_phases",
    "edit_changes_advancement",
    "edit_phase_result",
    "unwind_phase_result",
    "all_of",
    "top",
    "top_of_each_group",
    "places",
    "place",
]

_STANDINGS_FORMATS = ("round_robin", "swiss", "league")


# --------------------------------------------------------------------------------------
# SlotRef convenience constructors. A spec string is "phase" or "phase#group".
# --------------------------------------------------------------------------------------


def _split(spec: str) -> tuple[str, int | None]:
    if "#" in spec:
        phase, group = spec.split("#", 1)
        return phase, int(group)
    return spec, None


def all_of(spec: str) -> list[SlotRef]:
    """Every finisher of a phase (``"phase"``) or a specific group (``"phase#g"``)."""
    phase, group = _split(spec)
    return [SlotRef(phase, ALL_PLACES, group)]


def top(spec: str, n: int) -> list[SlotRef]:
    """The top ``n`` finishers of a phase or a specific group (``"phase#g"``)."""
    phase, group = _split(spec)
    return [SlotRef(phase, k, group) for k in range(1, n + 1)]


def top_of_each_group(phase: str, n: int) -> list[SlotRef]:
    """The top ``n`` of *every* group in a phase (sugar for grouped phases)."""
    return [SlotRef(phase, k, EACH_GROUP) for k in range(1, n + 1)]


def places(spec: str, lo: int, hi: int) -> list[SlotRef]:
    """Finishing places ``lo..hi`` (inclusive) of a phase or group."""
    phase, group = _split(spec)
    return [SlotRef(phase, k, group) for k in range(lo, hi + 1)]


def place(spec: str, p: int) -> SlotRef:
    """A single finishing place ``p`` of a phase or group."""
    phase, group = _split(spec)
    return SlotRef(phase, p, group)


# --------------------------------------------------------------------------------------
# Lookups and readiness
# --------------------------------------------------------------------------------------


def _phase(t: Tournament, phase_id: str) -> Phase:
    for p in t.phases:
        if p.id == phase_id:
            return p
    raise ValidationError(f"No phase with id {phase_id!r}.")


def phase_is_complete(phase: Phase) -> bool:
    """True once every sub-bracket of the phase is complete (unlocks its dependents)."""
    return bool(phase.brackets) and all(is_complete(b) for b in phase.brackets)


def is_phase_draftable(t: Tournament, phase_id: str) -> bool:
    """A phase is draftable iff every phase named by its entrants is complete."""
    phase = _phase(t, phase_id)
    if phase.entrants is None:
        return False  # phase 0 is built at generation time, never drafted
    return all(phase_is_complete(_phase(t, ref.phase)) for ref in phase.entrants.sources)


# --------------------------------------------------------------------------------------
# Phase results (what a SlotRef resolves against)
# --------------------------------------------------------------------------------------


def _group_results(bracket: Bracket, group_index: int) -> list[Ranked]:
    if bracket.format in _STANDINGS_FORMATS:
        return [
            Ranked(s.participant_id, s.rank, group_index) for s in get_standings(bracket)
        ]
    placements = sorted(get_placements(bracket), key=lambda pl: pl.position)
    return [Ranked(pl.participant_id, pl.position, group_index) for pl in placements]


def _divisioned_league(phase: Phase) -> Bracket | None:
    """The phase's single bracket if it is a league split into >1 division, else None.

    A divisioned league keeps every team in one bracket (so cross-division games can exist), so
    its "groups" are division labels inside that bracket rather than separate sub-brackets.
    """
    if len(phase.brackets) == 1 and phase.brackets[0].format == "league":
        bracket = phase.brackets[0]
        if len(bracket.config.get("divisions") or []) > 1:
            return bracket
    return None


def _phase_group_count(phase: Phase) -> int:
    league = _divisioned_league(phase)
    if league is not None:
        return len(league.config["divisions"])
    return len(phase.brackets) if phase.brackets else phase.groups


def _group_size(phase: Phase, group: int) -> int:
    league = _divisioned_league(phase)
    if league is not None:
        return len(league.config["divisions"][group])
    return len(phase.brackets[group].participants)


def _league_division_results(bracket: Bracket, division: int) -> list[Ranked]:
    from .formats.league import division_standings

    return [
        Ranked(s.participant_id, s.rank, division)
        for s in division_standings(bracket, division)
    ]


def phase_results(t: Tournament, phase_id: str, group: int | None = None) -> list[Ranked]:
    """Ranked finishers of a phase, overall (``group=None``) or for one group.

    Standings-based formats (round-robin, Swiss) rank by ``get_standings``; elimination
    formats by ``get_placements``. Only meaningful once the relevant bracket(s) are complete.
    """
    phase = _phase(t, phase_id)
    if group is not None:
        league = _divisioned_league(phase)
        if league is not None:
            return _league_division_results(league, group)
        return _group_results(phase.brackets[group], group)
    if len(phase.brackets) == 1:
        return _group_results(phase.brackets[0], 0)
    out: list[Ranked] = []
    for i, bracket in enumerate(phase.brackets):
        out.extend(_group_results(bracket, i))
    return out


# --------------------------------------------------------------------------------------
# Source resolution -> a seed order for the downstream phase
# --------------------------------------------------------------------------------------


def _placeholder(phase_id: str, group: int, place_: int, uid: int) -> Participant:
    """A stand-in finisher for previews, naming the upstream position it represents."""
    return Participant(
        id=uid,
        seed=place_,
        name=f"{phase_id} G{group}#{place_}",
        stats={"origin_phase": phase_id, "origin_group": group, "origin_place": place_,
               "placeholder": True},
    )


def _source_finishers(
    t: Tournament, phase_id: str, group: int | None, *, preview: bool, uid_base: int
) -> list[Participant]:
    """Rank-ordered finishers of a phase/group: real participants, or placeholders for a
    preview / a source that has not finished yet."""
    phase = _phase(t, phase_id)
    real = not preview and phase_is_complete(phase)
    if real:
        by_id = {p.id: p for p in t.participants}
        return [by_id[r.participant_id] for r in phase_results(t, phase_id, group)]

    # Placeholder path: size each group from its built bracket.
    if not phase.brackets:
        raise BracketStateError(
            f"Cannot preview against phase {phase_id!r}: its brackets are not built yet."
        )
    g = 0 if group is None else group
    size = _group_size(phase, g)
    return [_placeholder(phase_id, g, k, uid_base - k) for k in range(1, size + 1)]


def _expand_groups(ref: SlotRef, phase: Phase) -> list[int | None]:
    if ref.group == EACH_GROUP:
        return list(range(_phase_group_count(phase)))
    return [ref.group]


def _resolve(
    t: Tournament, qual: Qualification, *, preview: bool
) -> tuple[list[Participant], list[list[Participant]]]:
    """Resolve a Qualification into (seed_order, ranked_by_source).

    ``ranked_by_source`` is one rank-ordered list per distinct origin (phase, group), in
    source order — the input to the merge seeder and the rematch-avoidance repair.
    """
    order_keys: list[tuple[str, int | None]] = []
    chosen: dict[tuple[str, int | None], tuple[list[Participant], set[Any]]] = {}
    given_order: list[Participant] = []

    for src_idx, ref in enumerate(qual.sources):
        phase = _phase(t, ref.phase)
        for group in _expand_groups(ref, phase):
            key = (ref.phase, group)
            if key not in chosen:
                # Materialize a source's finishers exactly once, so every ref that selects
                # from it (e.g. top_of_each_group emits one ref per place) shares the same
                # objects and placeholder ids.
                uid_base = -((src_idx + 1) * 1_000_000 + ((group or 0) + 1) * 1000)
                chosen[key] = (
                    _source_finishers(t, ref.phase, group, preview=preview, uid_base=uid_base),
                    set(),
                )
                order_keys.append(key)
            finishers, ids = chosen[key]

            if ref.place == ALL_PLACES:
                selected = finishers
            elif ref.place - 1 < len(finishers):
                selected = [finishers[ref.place - 1]]
            else:
                raise ValidationError(
                    f"SlotRef place {ref.place} exceeds size {len(finishers)} of "
                    f"{ref.phase!r} group {group}."
                )
            for p in selected:
                ids.add(p.id)
                given_order.append(p)

    ranked_by_source: list[list[Participant]] = []
    for key in order_keys:
        finishers, ids = chosen[key]
        ranked_by_source.append([p for p in finishers if p.id in ids])

    seeding = qual.seeding
    if seeding == "manual":
        seen: set[Any] = set()
        seed_order: list[Participant] = []
        for p in given_order:
            if p.id not in seen:
                seen.add(p.id)
                seed_order.append(p)
    else:
        max_len = max((len(s) for s in ranked_by_source), default=0)
        seed_order = qualifier_seed_order(
            ranked_by_source, max_len, snake_shuffle=(seeding == "snake")
        )
    return seed_order, ranked_by_source


# --------------------------------------------------------------------------------------
# Bracket construction
# --------------------------------------------------------------------------------------


def _reseed(order: list[Participant]) -> list[Participant]:
    """Fresh participants seeded 1..N in the given order, deduped by id."""
    seen: set[Any] = set()
    out: list[Participant] = []
    n = 1
    for p in order:
        if p.id in seen:
            continue
        seen.add(p.id)
        out.append(Participant(id=p.id, seed=n, name=p.name, stats=dict(p.stats)))
        n += 1
    return out


def _build_one(
    fmt: str,
    parts: list[Participant],
    config: dict[str, Any],
    state: BracketState,
    *,
    pool_index: int | None,
    ranked_by_source: list[list[Participant]] | None,
) -> Bracket:
    if fmt == "round_robin":
        return generate_round_robin(parts, state=state, pool_index=pool_index)
    if fmt == "swiss":
        return generate_swiss(parts, rounds=config.get("rounds"), state=state)
    if fmt == "gauntlet":
        return generate_gauntlet(
            parts,
            style=config.get("style", "single"),
            opponent_choice=bool(config.get("opponent_choice", False)),
            choice_scope=config.get("choice_scope", "round"),
            state=state,
        )
    if fmt in ("single_elim", "double_elim"):
        ordered = sorted(parts, key=lambda p: p.seed)
        slots = seed_slots(ordered, next_power_of_2(len(ordered)))
        if ranked_by_source is not None and len(ranked_by_source) > 1:
            repair_first_round(slots, ranked_by_source)
        if fmt == "single_elim":
            survivors = config.get("survivors")
            return build_single_elim(
                slots,
                ordered,
                third_place_match=bool(config.get("third_place_match", False)),
                state=state,
                survivors=int(survivors) if survivors is not None else None,
            )
        return build_double_elim(
            slots,
            ordered,
            grand_final_reset=bool(config.get("grand_final_reset", True)),
            state=state,
        )
    raise ValidationError(f"Unsupported phase format: {fmt!r}")


def _build_brackets(
    seed_order: list[Participant],
    ranked_by_source: list[list[Participant]],
    phase: Phase,
    state: BracketState,
    *,
    repair: bool,
) -> list[Bracket]:
    reseeded = _reseed(seed_order)
    if len(reseeded) < 2:
        raise ValidationError(
            f"Phase {phase.id!r} resolved to {len(reseeded)} entrants; need at least 2."
        )
    if phase.format == "league":
        # A league owns its own divisions internally (one bracket), so cross-division games can
        # exist; ``groups`` is the division count, not a request for separate per-group brackets.
        return [_build_league(reseeded, phase, state)]
    if phase.groups > 1:
        assignment = snake_pool_assignment(reseeded, phase.groups)
        return [
            _build_one(
                phase.format, group, phase.config, state,
                pool_index=i, ranked_by_source=None,
            )
            for i, group in enumerate(assignment)
        ]
    return [
        _build_one(
            phase.format, reseeded, phase.config, state,
            pool_index=None,
            ranked_by_source=ranked_by_source if repair else None,
        )
    ]


def _build_league(parts: list[Participant], phase: Phase, state: BracketState) -> Bracket:
    from .formats.league import generate_league
    from .models.points import PointsSystem

    ps = phase.config.get("points_system")
    if isinstance(ps, dict):
        ps = PointsSystem.from_spec(ps)
    return generate_league(
        parts,
        divisions=max(1, phase.groups),
        best_of=int(phase.config.get("best_of", 1)),
        points=ps,
        state=state,
    )


# --------------------------------------------------------------------------------------
# Generation and lifecycle
# --------------------------------------------------------------------------------------


def generate_tournament(
    participants: list[Participant], phases: list[PhaseSpec]
) -> Tournament:
    """Build a multi-stage tournament. Phase 0 is seeded live from ``participants`` and
    published; every later phase carries its wiring but stays empty/``DRAFT`` until draftable.
    """
    validate_participants(participants)
    if not phases:
        raise ValidationError("A tournament needs at least one phase.")

    ids = [s.id for s in phases]
    if len(set(ids)) != len(ids):
        raise ValidationError("Phase ids must be unique.")

    seen: set[str] = set()
    built: list[Phase] = []
    for i, spec in enumerate(phases):
        if spec.groups < 1:
            raise ValidationError(f"Phase {spec.id!r}: groups must be >= 1.")
        if spec.entrants is None:
            if i != 0:
                raise ValidationError(
                    f"Phase {spec.id!r}: only the first phase may seed from the field."
                )
            field = sorted(participants, key=lambda p: p.seed)
            phase = Phase(
                id=spec.id, format=spec.format, config=dict(spec.config),
                entrants=None, groups=spec.groups,
                group_assignment=spec.group_assignment,
                brackets=[], state=BracketState.PUBLISHED,
            )
            phase.brackets = _build_brackets(
                field, [field], phase, BracketState.PUBLISHED, repair=False
            )
        else:
            for ref in spec.entrants.sources:
                if ref.phase not in seen:
                    raise ValidationError(
                        f"Phase {spec.id!r} references {ref.phase!r}, which is not an "
                        "earlier phase."
                    )
            phase = Phase(
                id=spec.id, format=spec.format, config=dict(spec.config),
                entrants=spec.entrants, groups=spec.groups,
                group_assignment=spec.group_assignment,
                brackets=[], state=BracketState.DRAFT,
            )
        seen.add(spec.id)
        built.append(phase)

    return Tournament(phases=built, participants=list(participants), config={})


def _with_phase(t: Tournament, phase_id: str, builder: Any) -> Tournament:
    """Return a deep copy of ``t`` with ``builder(phase)`` applied to the named phase."""
    new = copy.deepcopy(t)
    builder(_phase(new, phase_id))
    return new


def draft_phase(
    t: Tournament, phase_id: str, new_seed_order: list[Any] | None = None
) -> Tournament:
    """Resolve a phase's entrants from finished upstream results and build it in ``DRAFT``.

    The bracket(s) are fully built and settled but left ``DRAFT`` so the TO can review (and,
    via ``new_seed_order`` — a list of participant ids, seed 1 first — reorder) before
    publishing. Requires every source phase to be complete.
    """
    phase = _phase(t, phase_id)
    if phase.entrants is None:
        raise ValidationError(f"Phase {phase_id!r} is the field phase; it is not drafted.")
    if not is_phase_draftable(t, phase_id):
        raise BracketStateError(
            f"Phase {phase_id!r} is not draftable: its source phases are not all complete."
        )

    seed_order, ranked_by_source = _resolve(t, phase.entrants, preview=False)
    repair = phase.entrants.seeding == "snake"
    if new_seed_order is not None:
        by_id = {p.id: p for p in seed_order}
        seed_order = [by_id[pid] for pid in new_seed_order]
        ranked_by_source = [seed_order]
        repair = False

    brackets = _build_brackets(seed_order, ranked_by_source, phase, BracketState.DRAFT,
                               repair=repair)

    def apply(p: Phase) -> None:
        p.brackets = brackets
        p.state = BracketState.DRAFT

    return _with_phase(t, phase_id, apply)


def preview_phase(t: Tournament, phase_id: str) -> Tournament:
    """Build a preliminary ``DRAFT`` for a phase using placeholder qualifiers, before its
    sources have finished. Each bracket is flagged ``config["preview"] = True``."""
    phase = _phase(t, phase_id)
    if phase.entrants is None:
        raise ValidationError(f"Phase {phase_id!r} is the field phase; nothing to preview.")

    seed_order, ranked_by_source = _resolve(t, phase.entrants, preview=True)
    repair = phase.entrants.seeding == "snake"
    brackets = _build_brackets(seed_order, ranked_by_source, phase, BracketState.DRAFT,
                               repair=repair)
    for b in brackets:
        b.config["preview"] = True

    def apply(p: Phase) -> None:
        p.brackets = brackets
        p.state = BracketState.DRAFT

    return _with_phase(t, phase_id, apply)


def publish_phase(t: Tournament, phase_id: str) -> Tournament:
    """Flip a ``DRAFT`` phase to ``PUBLISHED``, re-settling its bracket(s) for play."""
    phase = _phase(t, phase_id)
    if phase.state is not BracketState.DRAFT or not phase.brackets:
        raise BracketStateError(f"Phase {phase_id!r} must be a built DRAFT to publish.")
    if any(b.config.get("preview") for b in phase.brackets):
        raise BracketStateError(
            f"Phase {phase_id!r} holds a preview; call draft_phase before publishing."
        )

    def apply(p: Phase) -> None:
        for b in p.brackets:
            b.state = BracketState.PUBLISHED
            settle_initial(b)
        p.state = BracketState.PUBLISHED

    return _with_phase(t, phase_id, apply)


def revert_phase(t: Tournament, phase_id: str) -> Tournament:
    """Tear a downstream phase back to empty/``DRAFT`` (the explicit teardown valve used
    before unwinding a completed upstream result that changes who advances)."""
    phase = _phase(t, phase_id)
    if phase.entrants is None:
        raise ValidationError(f"Phase {phase_id!r} is the field phase; it cannot be reverted.")

    def apply(p: Phase) -> None:
        p.brackets = []
        p.state = BracketState.DRAFT

    return _with_phase(t, phase_id, apply)


def advance_phase(
    t: Tournament, phase_id: str, new_seed_order: list[Any] | None = None
) -> Tournament:
    """Convenience: draft a phase from upstream results and publish it in one step."""
    return publish_phase(draft_phase(t, phase_id, new_seed_order), phase_id)


# --------------------------------------------------------------------------------------
# Cross-phase edit / unwind gate (MULTISTAGE_DESIGN.md §11)
# --------------------------------------------------------------------------------------


def _referencing_phases(t: Tournament, phase_id: str) -> list[Phase]:
    """Phases whose entrants directly reference ``phase_id``."""
    return [
        p
        for p in t.phases
        if p.entrants is not None and any(s.phase == phase_id for s in p.entrants.sources)
    ]


def _is_live(phase: Phase) -> bool:
    """A phase is live once its bracket(s) have been built (drafted/published/complete)."""
    return bool(phase.brackets)


def dependent_phases(
    t: Tournament, phase_id: str, *, transitive: bool = False, live_only: bool = False
) -> list[str]:
    """Ids of phases that draw (directly, or transitively) from ``phase_id``."""
    order = {p.id: i for i, p in enumerate(t.phases)}
    collected: set[str] = set()
    queue = [p.id for p in _referencing_phases(t, phase_id)]
    while queue:
        cur = queue.pop()
        if cur in collected:
            continue
        collected.add(cur)
        if transitive:
            queue.extend(p.id for p in _referencing_phases(t, cur))
    if live_only:
        collected = {pid for pid in collected if _is_live(_phase(t, pid))}
    return sorted(collected, key=lambda pid: order[pid])


def _live_downstream(t: Tournament, roots: list[str]) -> list[str]:
    """Roots plus everything transitively below them that is live (the revert set)."""
    order = {p.id: i for i, p in enumerate(t.phases)}
    collected: set[str] = set()
    seen: set[str] = set()
    queue = list(roots)
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if _is_live(_phase(t, cur)):
            collected.add(cur)
        queue.extend(p.id for p in _referencing_phases(t, cur))
    return sorted(collected, key=lambda pid: order[pid])


def _resolved_ids(t: Tournament, phase: Phase) -> list[Any]:
    assert phase.entrants is not None
    seed_order, _ = _resolve(t, phase.entrants, preview=False)
    return [p.id for p in seed_order]


def _apply_edit(
    t: Tournament,
    phase_id: str,
    match_id: int,
    new_winner_id: Any,
    group: int,
    advancement_type: AdvancementType,
    metadata: dict[str, Any] | None,
) -> Tournament:
    new_t = copy.deepcopy(t)
    phase = _phase(new_t, phase_id)
    if group >= len(phase.brackets):
        raise ValidationError(f"Phase {phase_id!r} has no group {group}.")
    bracket, _signals = unwind_result(phase.brackets[group], match_id)
    phase.brackets[group] = report_result(
        bracket, match_id, new_winner_id, advancement_type, metadata
    )
    return new_t


def edit_changes_advancement(
    t: Tournament,
    phase_id: str,
    match_id: int,
    new_winner_id: Any,
    *,
    group: int = 0,
    advancement_type: AdvancementType = AdvancementType.RESULT,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Live dependent phases that this edit would invalidate (empty = safe to apply).

    Recomputes each live dependent's resolved qualifiers/seeding before and after the edit; a
    dependent is invalidated only if a different participant qualifies or a qualifier's seed
    changes. If the edit leaves the source incomplete, every live dependent is invalidated.
    """
    src = _phase(t, phase_id)
    live_direct = [p for p in _referencing_phases(t, phase_id) if _is_live(p)]
    if not live_direct:
        return []
    if not phase_is_complete(src):
        return _live_downstream(t, [p.id for p in live_direct])

    before = {p.id: _resolved_ids(t, p) for p in live_direct}
    new_t = _apply_edit(t, phase_id, match_id, new_winner_id, group, advancement_type, metadata)
    if not phase_is_complete(_phase(new_t, phase_id)):
        return _live_downstream(t, [p.id for p in live_direct])

    changed = [
        pid for pid in before if before[pid] != _resolved_ids(new_t, _phase(new_t, pid))
    ]
    return _live_downstream(t, changed)


def edit_phase_result(
    t: Tournament,
    phase_id: str,
    match_id: int,
    new_winner_id: Any,
    *,
    group: int = 0,
    advancement_type: AdvancementType = AdvancementType.RESULT,
    metadata: dict[str, Any] | None = None,
) -> Tournament:
    """Correct a reported result in a phase (unwind + re-report), guarded against silently
    invalidating live downstream play.

    If the correction changes who advances (or a qualifier's seed) into any live dependent
    phase, this raises and names the phases to ``revert_phase`` first — the TO's explicit
    teardown. A correction that only reorders non-qualifiers, or is otherwise advancement-neutral,
    is applied with dependents left intact. The new result must keep the source phase complete.
    """
    blocked = edit_changes_advancement(
        t, phase_id, match_id, new_winner_id,
        group=group, advancement_type=advancement_type, metadata=metadata,
    )
    if blocked:
        raise BracketStateError(
            f"Editing match {match_id} in phase {phase_id!r} changes who advances; "
            f"revert_phase {blocked} first, then retry."
        )
    return _apply_edit(t, phase_id, match_id, new_winner_id, group, advancement_type, metadata)


def unwind_phase_result(
    t: Tournament, phase_id: str, match_id: int, *, group: int = 0
) -> tuple[Tournament, list[UnwindSignal]]:
    """Unwind a reported result in a phase, leaving it incomplete.

    Refused while any dependent phase is live, because an unwind makes the source incomplete and
    strands anything drafted from it. ``revert_phase`` those dependents first, or use
    :func:`edit_phase_result` when the corrected result does not change who advances.
    """
    live = dependent_phases(t, phase_id, live_only=True)
    if live:
        blocked = dependent_phases(t, phase_id, transitive=True, live_only=True)
        raise BracketStateError(
            f"Cannot unwind a result in phase {phase_id!r} while dependent phase(s) {blocked} "
            "are live. revert_phase them first, or use edit_phase_result if the corrected "
            "result does not change who advances."
        )
    new_t = copy.deepcopy(t)
    phase = _phase(new_t, phase_id)
    if group >= len(phase.brackets):
        raise ValidationError(f"Phase {phase_id!r} has no group {group}.")
    bracket, signals = unwind_result(phase.brackets[group], match_id)
    phase.brackets[group] = bracket
    return new_t, signals
