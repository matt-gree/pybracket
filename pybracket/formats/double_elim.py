from __future__ import annotations

from typing import Any

from ..advancement.engine import settle_initial
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState
from ..models.match import Match
from ..models.participant import Participant
from ..models.round import Round
from ..naming.round_names import (
    grand_final_round_name,
    losers_round_name,
    winners_round_name,
)
from ..seeding.algorithms import (
    ORDERINGS,
    assert_protected_seeds,
    seed_slots,
    standard_bracket_positions,
)
from ..utils.math import log2_int, next_power_of_2
from ..utils.validation import validate_participants
from .base import IdGen, build_standard_bracket, make_match

__all__ = ["generate_double_elim", "build_double_elim"]

# Ported from brackets-manager.js src/ordering.ts `defaultMinorOrdering` (MIT).
# Index 0 is the major (first LB round) ordering; the rest are the minor-round orderings.
DEFAULT_MINOR_ORDERING: dict[int, list[str]] = {
    4: ["natural", "reverse"],
    8: ["natural", "reverse", "natural"],
    16: ["natural", "reverse_half_shift", "reverse", "natural"],
    32: ["natural", "reverse", "half_shift", "natural", "natural"],
    64: ["natural", "reverse", "half_shift", "reverse", "natural", "natural"],
    128: ["natural", "reverse", "half_shift", "pair_flip", "pair_flip", "pair_flip", "natural"],
}

# A source describes where a losers-bracket slot's participant comes from.
Source = tuple[str, int]  # ('winner' | 'loser', match_id)


def _major_ordering(size: int) -> str:
    table = DEFAULT_MINOR_ORDERING.get(size)
    return table[0] if table else "natural"


def _minor_ordering(size: int, index: int, round_pair_count: int) -> str | None:
    # The last minor round orders a single participant, so no ordering is needed.
    if index == round_pair_count - 1:
        return None
    table = DEFAULT_MINOR_ORDERING.get(size)
    if table and 1 + index < len(table):
        return table[1 + index]
    return "natural"


def build_double_elim(
    ordered_slots: list[Participant | None],
    participants: list[Participant],
    grand_final_reset: bool = True,
    state: BracketState = BracketState.PUBLISHED,
    config: dict[str, Any] | None = None,
) -> Bracket:
    """Build a double-elimination bracket from a pre-ordered slot list (length = power of 2)."""
    size = len(ordered_slots)
    id_gen = IdGen()

    wb_matches, wb_round_ids, wb_final_id = build_standard_bracket(
        ordered_slots, id_gen, BracketSide.WINNERS
    )
    matches: list[Match] = list(wb_matches)
    by_id: dict[int, Match] = {m.id: m for m in matches}
    num_wb_rounds = len(wb_round_ids)

    rounds: list[Round] = [
        Round(
            number=i + 1,
            bracket_side=BracketSide.WINNERS,
            match_ids=list(ids),
            name=winners_round_name(i + 1, num_wb_rounds),
        )
        for i, ids in enumerate(wb_round_ids)
    ]

    # Fewer than three participants: no losers bracket / grand final is necessary.
    if size <= 2:
        bracket = _finalize(participants, matches, rounds, grand_final_reset, state, config)
        return bracket

    def create_lb_round(
        round_number: int, duels: list[tuple[Source, Source]]
    ) -> list[int]:
        ids: list[int] = []
        for src_a, src_b in duels:
            m = make_match(id_gen(), round_number, BracketSide.LOSERS)
            matches.append(m)
            by_id[m.id] = m
            ids.append(m.id)
            for src in (src_a, src_b):
                kind, src_id = src
                if kind == "loser":
                    by_id[src_id].next_loser_match_id = m.id
                else:
                    by_id[src_id].next_winner_match_id = m.id
        return ids

    round_pair_count = num_wb_rounds - 1

    # Initial LB duels: WB round-1 losers, ordered by the major method, paired up.
    major_method = _major_ordering(size)
    wb_r1_losers: list[Source] = [("loser", mid) for mid in wb_round_ids[0]]
    ordered_losers = ORDERINGS[major_method](wb_r1_losers)
    duels: list[tuple[Source, Source]] = [
        (ordered_losers[i], ordered_losers[i + 1])
        for i in range(0, len(ordered_losers), 2)
    ]

    lb_round_ids: list[list[int]] = []
    lb_round_number = 1
    prev_ids: list[int] = []
    losers_index = 1  # next WB round whose losers drop in

    for i in range(round_pair_count):
        match_count = 2 ** (round_pair_count - i - 1)

        # --- Major round ---
        if i == 0 and len(duels) == match_count:
            major_duels = duels
        else:
            major_duels = [
                (("winner", prev_ids[2 * j]), ("winner", prev_ids[2 * j + 1]))
                for j in range(match_count)
            ]
        major_ids = create_lb_round(lb_round_number, major_duels)
        lb_round_ids.append(major_ids)
        lb_round_number += 1
        prev_ids = major_ids

        # --- Minor round: WB losers of the next round drop in against major winners ---
        minor_method = _minor_ordering(size, i, round_pair_count)
        wb_losers: list[Source] = [("loser", mid) for mid in wb_round_ids[losers_index]]
        ordered_minor = ORDERINGS[minor_method](wb_losers) if minor_method else wb_losers
        minor_duels = [
            (ordered_minor[d], ("winner", prev_ids[d])) for d in range(match_count)
        ]
        minor_ids = create_lb_round(lb_round_number, minor_duels)
        lb_round_ids.append(minor_ids)
        lb_round_number += 1
        losers_index += 1
        prev_ids = minor_ids

    lb_final_id = prev_ids[0]
    num_lb_rounds = len(lb_round_ids)
    for i, ids in enumerate(lb_round_ids):
        rounds.append(
            Round(
                number=i + 1,
                bracket_side=BracketSide.LOSERS,
                match_ids=list(ids),
                name=losers_round_name(i + 1, num_lb_rounds),
            )
        )

    # --- Grand final (+ reset slot) ---
    gf = make_match(id_gen(), 1, BracketSide.GRAND_FINAL)
    matches.append(gf)
    by_id[gf.id] = gf
    by_id[wb_final_id].next_winner_match_id = gf.id
    by_id[lb_final_id].next_winner_match_id = gf.id
    rounds.append(
        Round(
            number=1,
            bracket_side=BracketSide.GRAND_FINAL,
            match_ids=[gf.id],
            name=grand_final_round_name(1),
        )
    )

    reset = make_match(id_gen(), 2, BracketSide.GRAND_FINAL)
    matches.append(reset)
    rounds.append(
        Round(
            number=2,
            bracket_side=BracketSide.GRAND_FINAL,
            match_ids=[reset.id],
            name=grand_final_round_name(2),
        )
    )

    return _finalize(participants, matches, rounds, grand_final_reset, state, config)


def _finalize(
    participants: list[Participant],
    matches: list[Match],
    rounds: list[Round],
    grand_final_reset: bool,
    state: BracketState,
    config: dict[str, Any] | None,
) -> Bracket:
    cfg: dict[str, Any] = {"grand_final_reset": grand_final_reset}
    if config:
        cfg.update(config)
    bracket = Bracket(
        format="double_elim",
        state=state,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config=cfg,
    )
    settle_initial(bracket)
    return bracket


def generate_double_elim(
    participants: list[Participant],
    grand_final_reset: bool = True,
    protected_seeds: int = 0,
) -> Bracket:
    """Generate a double-elimination bracket with losers bracket and grand final."""
    validate_participants(participants)
    ordered = sorted(participants, key=lambda p: p.seed)
    size = next_power_of_2(len(ordered))
    log2_int(size)  # assert power of two

    if protected_seeds:
        positions = standard_bracket_positions(size)
        seed_at_slot: list[int | None] = [
            pos if pos <= len(ordered) else None for pos in positions
        ]
        assert_protected_seeds(seed_at_slot, protected_seeds, size)

    slots = seed_slots(ordered, size)
    return build_double_elim(
        slots,
        participants,
        grand_final_reset=grand_final_reset,
        config={"protected_seeds": protected_seeds},
    )
