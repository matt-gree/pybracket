from __future__ import annotations

from typing import Any

from ..advancement.engine import settle_initial
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState
from ..models.participant import Participant
from ..models.round import Round
from ..naming.round_names import single_elim_round_name
from ..seeding.algorithms import assert_protected_seeds, seed_slots, standard_bracket_positions
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
) -> Bracket:
    """Generate a single-elimination bracket. Top seeds receive byes."""
    validate_participants(participants)
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
