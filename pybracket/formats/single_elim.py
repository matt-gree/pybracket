from __future__ import annotations

from typing import Any, cast

from ..advancement.engine import settle_initial
from ..errors import ValidationError
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState
from ..models.match import Match
from ..models.participant import Participant
from ..models.round import Round
from ..naming.round_names import single_elim_round_name
from ..seeding.algorithms import assert_protected_seeds, seed_slots, standard_bracket_positions
from ..seeding.byes import (
    ByeCompletion,
    ByeNode,
    MatchNode,
    build_bye_plan,
    complete_bye_rounds,
)
from ..utils.math import next_power_of_2
from ..utils.validation import validate_participants
from .base import IdGen, build_standard_bracket, make_match

__all__ = ["generate_single_elim", "build_single_elim"]


def build_single_elim(
    ordered_slots: list[Participant | None],
    participants: list[Participant],
    third_place_match: bool = False,
    state: BracketState = BracketState.PUBLISHED,
    config: dict[str, Any] | None = None,
) -> Bracket:
    """Build a single-elimination bracket from a pre-ordered slot list (length = power of 2)."""
    id_gen = IdGen()
    matches, round_match_ids, final_id = build_standard_bracket(
        ordered_slots, id_gen, BracketSide.WINNERS
    )
    by_id = {m.id: m for m in matches}
    num_rounds = len(round_match_ids)

    rounds: list[Round] = []
    for r_index, ids in enumerate(round_match_ids):
        rounds.append(
            Round(
                number=r_index + 1,
                bracket_side=BracketSide.WINNERS,
                match_ids=list(ids),
                name=single_elim_round_name(r_index + 1, num_rounds),
            )
        )

    if third_place_match and num_rounds >= 2:
        # Semifinal round is the one feeding the final (two matches).
        semifinal_ids = round_match_ids[num_rounds - 2]
        third = make_match(
            id_gen(),
            num_rounds + 1,
            BracketSide.WINNERS,
            metadata={"consolation": True},
        )
        matches.append(third)
        for sid in semifinal_ids:
            by_id[sid].next_loser_match_id = third.id
        rounds.append(
            Round(
                number=num_rounds + 1,
                bracket_side=BracketSide.WINNERS,
                match_ids=[third.id],
                name="Third Place Match",
            )
        )

    cfg: dict[str, Any] = {"third_place_match": third_place_match}
    if config:
        cfg.update(config)

    bracket = Bracket(
        format="single_elim",
        state=state,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config=cfg,
    )
    settle_initial(bracket)
    return bracket


def generate_single_elim(
    participants: list[Participant],
    third_place_match: bool = False,
    protected_seeds: int = 0,
    bye_rounds: dict[int, int] | None = None,
) -> Bracket:
    """Generate a single-elimination bracket.

    ``bye_rounds`` maps a seed number to the number of *rounds* that seed skips before its
    first match. ``None`` (the default) keeps the classic behaviour: the field is rounded up
    to the next power of two and the top seeds receive a single round of byes for any empty
    slots.

    Providing a mapping lets the TO specify only the byes they care about — e.g.
    ``{1: 2, 2: 2, 3: 2, 4: 2}`` for "the top four seeds get a double bye". The engine completes
    the configuration, adding the minimal extra byes needed to reach a workable bracket (here,
    single byes for seeds 5–8), and records what it added in ``config["bye_rounds_added"]``.
    The completed per-seed map respects seeding (seeds 1 and 2 land in opposite halves) and is
    stored in ``config["bye_rounds"]``. With enough byes the bracket degenerates into a gauntlet
    (each higher seed gets exactly one more bye than the next), a valid point on the same
    continuum. Use :func:`pybracket.allowable_bye_options` to discover the configurations a
    field size supports.
    """
    validate_participants(participants)

    if bye_rounds is not None:
        if protected_seeds:
            raise ValidationError(
                "protected_seeds and bye_rounds cannot be combined; bye_rounds fully "
                "determines the round structure."
            )
        return _build_bye_rounds_single_elim(participants, bye_rounds, third_place_match)

    ordered = sorted(participants, key=lambda p: p.seed)
    size = next_power_of_2(len(ordered))

    if protected_seeds:
        positions = standard_bracket_positions(size)
        seed_at_slot: list[int | None] = [
            pos if pos <= len(ordered) else None for pos in positions
        ]
        assert_protected_seeds(seed_at_slot, protected_seeds, size)

    slots = seed_slots(ordered, size)
    return build_single_elim(
        slots,
        participants,
        third_place_match=third_place_match,
        config={"protected_seeds": protected_seeds},
    )


# --------------------------------------------------------------------------------------
# N-level byes
# --------------------------------------------------------------------------------------

# The result of emitting a plan node: a seated seed, or the winner of an already-built match.
_Emitted = tuple[str, Any]  # ("seed", Participant) | ("match", match_id)


def _attach_emitted(match: Match, child: _Emitted, by_id: dict[int, Match]) -> None:
    """Seat an entering seed in the match, or wire a feeder match's winner toward it."""
    kind, value = child
    if kind == "seed":
        if match.participant1_id is None:
            match.participant1_id = value.id
        else:
            match.participant2_id = value.id
    else:  # feeder match id
        by_id[value].next_winner_match_id = match.id


def _emit_plan(
    node: ByeNode,
    by_seed: dict[int, Participant],
    id_gen: IdGen,
    matches: list[Match],
    by_id: dict[int, Match],
) -> _Emitted:
    """Walk a bye plan left-first, creating a match per internal node.

    Visiting the left subtree before the right (and creating each parent after its children)
    assigns match ids in top-to-bottom order within every round, so the emitted bracket renders
    cleanly: sibling matches stay adjacent and feed the same parent.
    """
    if node[0] == "seed":
        return ("seed", by_seed[node[1]])
    _, round_number, left, right = cast("MatchNode", node)
    left_emitted = _emit_plan(left, by_seed, id_gen, matches, by_id)
    right_emitted = _emit_plan(right, by_seed, id_gen, matches, by_id)
    match = make_match(id_gen(), round_number, BracketSide.WINNERS)
    _attach_emitted(match, left_emitted, by_id)
    _attach_emitted(match, right_emitted, by_id)
    matches.append(match)
    by_id[match.id] = match
    return ("match", match.id)


def _build_bye_rounds_single_elim(
    participants: list[Participant],
    bye_rounds: dict[int, int],
    third_place_match: bool,
) -> Bracket:
    """Build a single-elim tree from a (possibly partial) per-seed bye configuration.

    The request is completed into a configuration that tiles a perfect ``2**rounds`` bracket
    (see :func:`pybracket.complete_bye_rounds`), then laid out top-down in standard seed order.
    A clean power-of-two field with no byes falls through to the ordinary builder.
    """
    ordered = sorted(participants, key=lambda p: p.seed)
    completion: ByeCompletion = complete_bye_rounds(len(ordered), bye_rounds)
    config = _bye_config(third_place_match, completion)

    if max(completion.completed.values(), default=0) == 0:
        # No byes at all: identical to the standard power-of-two bracket.
        slots = seed_slots(ordered, next_power_of_2(len(ordered)))
        return build_single_elim(
            slots, participants, third_place_match=third_place_match, config=config
        )

    by_seed = {p.seed: p for p in ordered}
    plan = build_bye_plan(completion.completed)
    id_gen = IdGen()
    matches: list[Match] = []
    by_id: dict[int, Match] = {}
    root = _emit_plan(plan, by_seed, id_gen, matches, by_id)
    final_id = root[1]
    total_rounds = completion.rounds

    rounds: list[Round] = []
    for rn in range(1, total_rounds + 1):
        ids = [m.id for m in matches if m.round_number == rn]
        rounds.append(
            Round(
                number=rn,
                bracket_side=BracketSide.WINNERS,
                match_ids=ids,
                name=single_elim_round_name(rn, total_rounds),
            )
        )

    if third_place_match:
        final_feeders = [m for m in matches if m.next_winner_match_id == final_id]
        if len(final_feeders) != 2:
            raise ValidationError(
                "third_place_match requires the final to be fed by exactly two matches; the "
                "given bye_rounds does not produce that (e.g. a gauntlet where the top seed "
                "enters directly into the final)."
            )
        third = make_match(
            id_gen(), total_rounds + 1, BracketSide.WINNERS, metadata={"consolation": True}
        )
        matches.append(third)
        for feeder in final_feeders:
            feeder.next_loser_match_id = third.id
        rounds.append(
            Round(
                number=total_rounds + 1,
                bracket_side=BracketSide.WINNERS,
                match_ids=[third.id],
                name="Third Place Match",
            )
        )

    bracket = Bracket(
        format="single_elim",
        state=BracketState.PUBLISHED,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config=config,
    )
    settle_initial(bracket)
    return bracket


def _bye_config(third_place_match: bool, completion: ByeCompletion) -> dict[str, Any]:
    """Config block recording the completed byes and what the engine added to the request."""
    config: dict[str, Any] = {
        "third_place_match": third_place_match,
        "bye_rounds": dict(completion.completed),
    }
    if completion.added:
        config["bye_rounds_requested"] = {
            s: completion.requested.get(s, 0) for s in sorted(completion.requested)
        }
        config["bye_rounds_added"] = dict(completion.added)
    return config
