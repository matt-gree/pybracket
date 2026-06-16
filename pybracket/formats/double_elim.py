from __future__ import annotations

from typing import Any

from ..advancement.engine import compute_occupant_counts, settle_initial
from ..errors import ValidationError
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
from ..seeding.byes import ByeCompletion, complete_bye_rounds, expand_byes_to_slots
from ..utils.math import log2_int, next_power_of_2
from ..utils.validation import validate_participants
from .base import IdGen, build_standard_bracket, make_match

__all__ = ["generate_double_elim", "build_double_elim"]

# Double elimination supports custom byes only up to a double bye: deeper byes produce
# winners-bracket shapes whose losers-bracket drop pattern we don't model with confidence.
MAX_DOUBLE_ELIM_BYE_LEVEL = 2

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
    compact: bool = True,
) -> Bracket:
    """Build a double-elimination bracket from a pre-ordered slot list (length = power of 2).

    When the field has byes (empty slots), the power-of-two structure contains single-occupant
    bye matches that a participant merely passes through. With ``compact`` (the default) these
    are contracted into a compact bracket with no phantom matches (see :func:`_collapse_byes`);
    pass ``compact=False`` to keep the raw padded structure (the original, always-correct layout
    that the compact form is verified against).
    """
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
        return _collapse_byes(bracket) if compact else bracket

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

    bracket = _finalize(participants, matches, rounds, grand_final_reset, state, config)
    return _collapse_byes(bracket) if compact else bracket


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


def _is_reset(m: Match) -> bool:
    return m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2


def _collapse_byes(bracket: Bracket) -> Bracket:
    """Contract pass-through bye matches into a compact bracket the engine plays natively.

    The power-of-two construction leaves single-occupant *bye* matches (occupant count 1, a
    participant auto-advances through) and empty *phantom* matches (count 0) wherever the field
    has byes. They never host a real contest, so we drop them: every kept match's winner/loser
    pointers are rewired to skip the removed byes, rounds are renumbered from the resulting compact
    structure (so e.g. a heavily-byed losers bracket starts at round 1 instead of mid-bracket),
    round names are rebuilt, and statuses are re-settled. A clean power-of-two field has nothing to
    collapse and is returned unchanged. Play is unaffected — a bye only ever passed its lone
    participant straight through.
    """
    counts = compute_occupant_counts(bracket)
    by_id = {m.id: m for m in bracket.matches}
    kept_ids = {m.id for m in bracket.matches if counts[m.id] == 2 or _is_reset(m)}
    if len(kept_ids) == len(bracket.matches):
        return bracket  # clean power-of-two field: no byes to collapse

    def chase(start: int | None) -> int | None:
        """Follow winner advancement from ``start`` through removed byes to the next kept match."""
        seen: set[int] = set()
        cur = start
        while cur is not None and cur not in kept_ids and cur in by_id and cur not in seen:
            seen.add(cur)
            cur = by_id[cur].next_winner_match_id
        return cur if cur in kept_ids else None

    # Rewire kept matches past the removed byes. A winner advances via next_winner; a dropped
    # loser enters next_loser and (if that slot is a bye) byes onward through its winner.
    for mid in kept_ids:
        m = by_id[mid]
        m.next_winner_match_id = chase(m.next_winner_match_id)
        loser = m.next_loser_match_id
        m.next_loser_match_id = loser if loser in kept_ids else chase(loser)

    kept = [m for m in bracket.matches if m.id in kept_ids]

    # Renumber winners/losers rounds from the compact structure (distance to the side's final).
    # The grand final side keeps its numbering — the reset is identified by round_number == 2.
    for side in (BracketSide.WINNERS, BracketSide.LOSERS):
        side_by_id = {m.id: m for m in kept if m.bracket_side is side}
        if not side_by_id:
            continue

        def dist_to_final(m: Match, ids: dict[int, Match] = side_by_id) -> int:
            d, cur = 0, m
            while cur.next_winner_match_id in ids:
                cur = ids[cur.next_winner_match_id]
                d += 1
            return d

        dists = {m.id: dist_to_final(m) for m in side_by_id.values()}
        max_dist = max(dists.values())
        for m in side_by_id.values():
            m.round_number = max_dist - dists[m.id] + 1

    rounds = _rebuild_rounds(kept)
    new = Bracket(
        format=bracket.format,
        state=bracket.state,
        participants=list(bracket.participants),
        matches=kept,
        rounds=rounds,
        config=dict(bracket.config),
    )
    settle_initial(new)
    return new


def _rebuild_rounds(matches: list[Match]) -> list[Round]:
    """Rebuild Round metadata (ids + names) from matches whose round_number has been recomputed."""
    rounds: list[Round] = []
    for side in (BracketSide.WINNERS, BracketSide.LOSERS, BracketSide.GRAND_FINAL):
        side_ms = [m for m in matches if m.bracket_side is side]
        if not side_ms:
            continue
        numbers = sorted({m.round_number for m in side_ms})
        total = len(numbers)
        for rn in numbers:
            ids = [m.id for m in side_ms if m.round_number == rn]
            if side is BracketSide.WINNERS:
                name = winners_round_name(rn, total)
            elif side is BracketSide.LOSERS:
                name = losers_round_name(rn, total)
            else:
                name = grand_final_round_name(rn)
            rounds.append(Round(number=rn, bracket_side=side, match_ids=ids, name=name))
    return rounds


def generate_double_elim(
    participants: list[Participant],
    grand_final_reset: bool = True,
    protected_seeds: int = 0,
    bye_rounds: dict[int, int] | None = None,
    compact: bool = True,
) -> Bracket:
    """Generate a double-elimination bracket with losers bracket and grand final.

    ``bye_rounds`` maps a seed number to the number of rounds that seed skips before its first
    winners-bracket match, exactly as in :func:`pybracket.generate_single_elim`. ``None`` keeps
    the classic behaviour (round the field up to a power of two and give the top seeds a single
    round of byes for the empty slots). Custom byes are completed into a tiling configuration
    (see :func:`pybracket.complete_bye_rounds`), then laid out on the standard power-of-two
    winners/losers structure with the byed slots left empty — the engine resolves the byes and
    suppresses the loser-drops they would otherwise feed into the losers bracket. Byes deeper
    than a double bye are rejected; use :func:`pybracket.allowable_bye_options` with
    ``max_bye_level=2`` to discover the supported configurations.

    ``compact`` (the default) contracts the pass-through bye matches a byed field produces into a
    clean structure with no phantom matches, renumbered so the losers bracket starts at round 1.
    Pass ``compact=False`` to keep the raw power-of-two padded structure (with explicit bye
    matches) — the original layout, which the compact form is proven to play identically to.
    """
    validate_participants(participants)

    if bye_rounds is not None:
        if protected_seeds:
            raise ValidationError(
                "protected_seeds and bye_rounds cannot be combined; bye_rounds fully "
                "determines the round structure."
            )
        return _build_bye_rounds_double_elim(participants, bye_rounds, grand_final_reset, compact)

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
        compact=compact,
    )


def _build_bye_rounds_double_elim(
    participants: list[Participant],
    bye_rounds: dict[int, int],
    grand_final_reset: bool,
    compact: bool = True,
) -> Bracket:
    """Build a double-elim from a (possibly partial) per-seed bye configuration (byes <= 2).

    The request is completed into a tiling ``2**rounds`` configuration, expanded into a full slot
    list with the byed slots empty, and handed to the ordinary :func:`build_double_elim`. The
    occupant-count engine then auto-advances bye'd seeds through the winners bracket and skips the
    loser-drops those byes would have produced, so the losers bracket fills exactly as it would
    for the equivalent non-byed field.
    """
    ordered = sorted(participants, key=lambda p: p.seed)
    completion = complete_bye_rounds(len(ordered), bye_rounds)
    if max(completion.completed.values(), default=0) > MAX_DOUBLE_ELIM_BYE_LEVEL:
        raise ValidationError(
            "Double elimination supports byes of at most two rounds (a double bye). "
            "Use allowable_bye_options(n, max_bye_level=2) to see the configurations this "
            "field supports."
        )

    by_seed = {p.seed: p for p in ordered}
    slots: list[Participant | None] = [
        by_seed[s] if s is not None else None for s in expand_byes_to_slots(completion.completed)
    ]
    return build_double_elim(
        slots,
        participants,
        grand_final_reset=grand_final_reset,
        config=_bye_config(completion),
        compact=compact,
    )


def _bye_config(completion: ByeCompletion) -> dict[str, Any]:
    """Config block recording the completed byes and what the engine added to the request."""
    config: dict[str, Any] = {"bye_rounds": dict(completion.completed)}
    if completion.added:
        config["bye_rounds_requested"] = {
            s: completion.requested.get(s, 0) for s in sorted(completion.requested)
        }
        config["bye_rounds_added"] = dict(completion.added)
    return config
