from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from ..advancement.engine import is_complete, settle_initial
from ..errors import BracketStateError, ValidationError
from ..models.bracket import Bracket
from ..models.enums import BracketState
from ..models.participant import Participant
from ..seeding.algorithms import seed_slots
from ..seeding.pool_seeding import qualifier_slot_order, snake_pool_assignment
from ..tiebreakers.base import Tiebreaker
from ..tiebreakers.standings import get_standings, serialize_tiebreakers
from ..utils.math import next_power_of_2
from ..utils.validation import validate_participants
from .double_elim import build_double_elim
from .round_robin import generate_round_robin
from .single_elim import build_single_elim

__all__ = [
    "PoolsBracket",
    "generate_pools",
    "draft_pools_to_bracket",
    "preview_pools_bracket",
    "publish_bracket",
    "reseed_pools_to_bracket",
]


@dataclass
class PoolsBracket:
    pools: list[Bracket]
    elimination: Bracket
    participants: list[Participant]
    config: dict[str, Any] = field(default_factory=dict)


def _empty_elimination(bracket_format: str) -> Bracket:
    return Bracket(
        format=bracket_format,
        state=BracketState.DRAFT,
        participants=[],
        matches=[],
        rounds=[],
        config={},
    )


def generate_pools(
    participants: list[Participant],
    num_pools: int,
    advancement_count: int,
    bracket_format: str = "double_elim",
    snake_shuffle: bool = True,
    tiebreakers: list[Tiebreaker] | None = None,
    **bracket_kwargs: Any,
) -> PoolsBracket:
    """Generate round-robin pools; the elimination bracket stays DRAFT until pools finish."""
    validate_participants(participants)
    if num_pools < 1:
        raise ValidationError("num_pools must be >= 1.")
    if advancement_count < 1:
        raise ValidationError("advancement_count must be >= 1.")

    assignment = snake_pool_assignment(participants, num_pools)
    for i, pool in enumerate(assignment):
        if advancement_count > len(pool):
            raise ValidationError(
                f"advancement_count {advancement_count} exceeds pool {i} size {len(pool)}."
            )

    pools = [
        generate_round_robin(pool, tiebreakers=tiebreakers, pool_index=i)
        for i, pool in enumerate(assignment)
    ]

    config: dict[str, Any] = {
        "num_pools": num_pools,
        "advancement_count": advancement_count,
        "bracket_format": bracket_format,
        "snake_shuffle": snake_shuffle,
        "bracket_kwargs": dict(bracket_kwargs),
        "pool_sizes": [len(p) for p in assignment],
        "uneven_pools": len({len(p) for p in assignment}) > 1,
    }
    if tiebreakers is not None:
        config["tiebreakers"] = serialize_tiebreakers(tiebreakers)

    return PoolsBracket(
        pools=pools,
        elimination=_empty_elimination(bracket_format),
        participants=list(participants),
        config=config,
    )


def _build_elimination(
    slots: list[Participant | None],
    participants: list[Participant],
    bracket_format: str,
    bracket_kwargs: dict[str, Any],
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    if bracket_format == "single_elim":
        return build_single_elim(
            slots,
            participants,
            third_place_match=bool(bracket_kwargs.get("third_place_match", False)),
            state=state,
        )
    if bracket_format == "double_elim":
        return build_double_elim(
            slots,
            participants,
            grand_final_reset=bool(bracket_kwargs.get("grand_final_reset", True)),
            state=state,
        )
    raise ValidationError(f"Unsupported pool bracket_format: {bracket_format!r}")


def _draft_from_slots(
    slots: list[Participant | None],
    pools_bracket: PoolsBracket,
    advancing: list[Participant],
    *,
    preview: bool,
) -> PoolsBracket:
    """Reseed the occupied slots 1..N (by slot order) and build the DRAFT elimination bracket.

    Shared by :func:`draft_pools_to_bracket` (real qualifiers) and :func:`preview_pools_bracket`
    (origin placeholders); ``preview`` is recorded in config so callers can tell them apart.
    """
    bracket_format = str(pools_bracket.config["bracket_format"])
    bracket_kwargs = dict(pools_bracket.config.get("bracket_kwargs", {}))

    seed_counter = 1
    seen: set[Any] = set()
    reseeded: list[Participant] = []
    for slot in slots:
        if slot is None or slot.id in seen:
            continue
        seen.add(slot.id)
        reseeded.append(
            Participant(id=slot.id, seed=seed_counter, name=slot.name, stats=dict(slot.stats))
        )
        seed_counter += 1

    elimination = _build_elimination(
        slots, reseeded, bracket_format, bracket_kwargs, state=BracketState.DRAFT
    )

    new_config = dict(pools_bracket.config)
    new_config["advancing_ids"] = [p.id for p in advancing]
    new_config["preview"] = preview
    return PoolsBracket(
        pools=list(pools_bracket.pools),
        elimination=elimination,
        participants=list(pools_bracket.participants),
        config=new_config,
    )


def draft_pools_to_bracket(
    pools_bracket: PoolsBracket,
    new_seed_order: list[Any] | None = None,
) -> PoolsBracket:
    """Seed survivors from the finished pool standings into a DRAFT elimination bracket.

    The bracket is fully built and settled but left in ``BracketState.DRAFT`` so the TO can
    review (and, by passing ``new_seed_order``, reorder) the seeding before publishing it for
    play. Call :func:`publish_bracket` to lock it in. ``new_seed_order`` is a list of advancing
    participant ids in the desired seed order (seed 1 first).
    """
    for pool in pools_bracket.pools:
        if not is_complete(pool):
            raise BracketStateError("All pool matches must be complete before reseeding.")

    advancement_count = int(pools_bracket.config["advancement_count"])
    snake_shuffle = bool(pools_bracket.config.get("snake_shuffle", True))

    by_id = {p.id: p for p in pools_bracket.participants}
    ranked_by_pool: list[list[Participant]] = []
    for pool in pools_bracket.pools:
        standings = get_standings(pool)
        advancers = [by_id[s.participant_id] for s in standings[:advancement_count]]
        ranked_by_pool.append(advancers)

    if new_seed_order is not None:
        ordered = [by_id[pid] for pid in new_seed_order]
        size = next_power_of_2(len(ordered))
        slots = seed_slots(ordered, size)
        advancing = ordered
    else:
        slots = qualifier_slot_order(ranked_by_pool, advancement_count, snake_shuffle)
        advancing = [p for p in slots if p is not None]

    return _draft_from_slots(slots, pools_bracket, advancing, preview=False)


def _pool_label(index: int) -> str:
    """0 -> 'A', 1 -> 'B', ..., 25 -> 'Z', 26 -> 'AA' (matches the studio's pool labels)."""
    label = ""
    n = index
    while True:
        label = chr(65 + n % 26) + label
        n = n // 26 - 1
        if n < 0:
            break
    return label


def _placeholder(pool_index: int, place: int, advancement_count: int) -> Participant:
    """A stand-in qualifier for the preview bracket, naming the pool finish it represents.

    Ids are negative so they can never collide with the real participants (always positive),
    and the origin is carried in ``stats`` so a UI can label the slot however it likes.
    """
    return Participant(
        id=-(pool_index * advancement_count + place),
        seed=place,
        name=f"Pool {_pool_label(pool_index)} #{place}",
        stats={"origin_pool": pool_index, "origin_place": place, "placeholder": True},
    )


def preview_pools_bracket(pools_bracket: PoolsBracket) -> PoolsBracket:
    """Build a preliminary elimination bracket *before* the pools finish.

    Every slot is filled with a placeholder qualifier that names its origin ("Pool A #1") and
    records it in ``stats``, using the same snake-seed mapping the real draft uses — so the TO
    can see exactly where each pool finisher will land. The bracket is ``DRAFT`` and flagged
    ``config["preview"] = True``; rebuild it for real with :func:`draft_pools_to_bracket` once
    the pools are complete. Unlike the real draft, this never requires the pools to be played.
    """
    num_pools = int(pools_bracket.config["num_pools"])
    advancement_count = int(pools_bracket.config["advancement_count"])
    snake_shuffle = bool(pools_bracket.config.get("snake_shuffle", True))

    ranked_by_pool: list[list[Participant]] = [
        [_placeholder(pool_index, place, advancement_count) for place in range(1, advancement_count + 1)]
        for pool_index in range(num_pools)
    ]
    slots = qualifier_slot_order(ranked_by_pool, advancement_count, snake_shuffle)
    advancing = [p for p in slots if p is not None]
    return _draft_from_slots(slots, pools_bracket, advancing, preview=True)


def publish_bracket(pools_bracket: PoolsBracket) -> PoolsBracket:
    """Transition a DRAFT elimination bracket to PUBLISHED, locking it in for play.

    Re-settles the bracket (resolving construction-time byes and initial statuses) and flips
    its state to PUBLISHED. The pools and participants are carried over unchanged.
    """
    if pools_bracket.elimination.state is not BracketState.DRAFT:
        raise BracketStateError("Bracket must be in DRAFT state to publish.")

    elimination = copy.deepcopy(pools_bracket.elimination)
    elimination.state = BracketState.PUBLISHED
    # Re-run settlement now that the bracket is no longer DRAFT, so statuses/byes and the
    # PUBLISHED/COMPLETE transition resolve correctly.
    settle_initial(elimination)
    return PoolsBracket(
        pools=list(pools_bracket.pools),
        elimination=elimination,
        participants=list(pools_bracket.participants),
        config=dict(pools_bracket.config),
    )


def reseed_pools_to_bracket(
    pools_bracket: PoolsBracket,
    new_seed_order: list[Any] | None = None,
) -> PoolsBracket:
    """Convenience: draft the elimination bracket from pool results and publish it in one step.

    Equivalent to ``publish_bracket(draft_pools_to_bracket(pools_bracket, new_seed_order))``.
    Use the two-step flow directly when the TO needs to review or reorder seeds first.
    """
    return publish_bracket(draft_pools_to_bracket(pools_bracket, new_seed_order))
