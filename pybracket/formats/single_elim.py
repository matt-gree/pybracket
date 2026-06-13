from __future__ import annotations

from typing import Any

from ..advancement.engine import settle_initial
from ..errors import ValidationError
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState
from ..models.match import Match
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
    bye_rounds: dict[int, int] | None = None,
) -> Bracket:
    """Generate a single-elimination bracket.

    ``bye_rounds`` maps a seed number to the number of *rounds* that seed skips before its
    first match. ``None`` (the default) keeps the classic behaviour: the field is rounded up
    to the next power of two and the top seeds receive a single round of byes for any empty
    slots. Providing an explicit mapping lets the TO build multi-round byes — for example
    ``{1: 2, 2: 1, 3: 1}`` means seed 1 enters in round 3, seeds 2 and 3 enter in round 2, and
    everyone else plays a normal round 1. With enough byes the bracket degenerates into a
    gauntlet (each higher seed gets exactly one more bye than the next), which the library
    treats as a valid point on the same continuum.
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

# An item feeding a round's match: a seed entering for the first time, or the winner of a
# previously-built match (a "carry").
_Incoming = tuple[str, Any]  # ("seed", Participant) | ("feeder", match_id)


def _validate_bye_rounds(
    ordered: list[Participant], bye_rounds: dict[int, int]
) -> dict[int, int]:
    """Validate the raw mapping and return per-seed bye counts for every participant."""
    seeds_present = {p.seed for p in ordered}
    for seed, count in bye_rounds.items():
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValidationError(
                f"bye_rounds value for seed {seed} must be an integer, got {count!r}."
            )
        if count < 0:
            raise ValidationError(
                f"bye_rounds value for seed {seed} must be non-negative, got {count}."
            )
        if seed not in seeds_present:
            raise ValidationError(
                f"bye_rounds references seed {seed}, which has no matching participant."
            )

    byes_of = {p.seed: int(bye_rounds.get(p.seed, 0)) for p in ordered}

    # Byes must be monotonically non-increasing by seed: a worse seed can never receive more
    # byes than a better one (otherwise the structure no longer protects the top seeds).
    previous: int | None = None
    for p in ordered:  # ascending seed order (best first)
        current = byes_of[p.seed]
        if previous is not None and current > previous:
            raise ValidationError(
                f"bye_rounds must be non-increasing by seed: seed {p.seed} is given more byes "
                f"({current}) than a better-ranked seed ({previous})."
            )
        previous = current

    return byes_of


def _attach_incoming(match: Match, item: _Incoming, by_id: dict[int, Match]) -> None:
    """Either place an entering seed into the match, or wire a feeder's winner toward it."""
    kind, value = item
    if kind == "seed":
        if match.participant1_id is None:
            match.participant1_id = value.id
        else:
            match.participant2_id = value.id
    else:  # feeder match id
        by_id[value].next_winner_match_id = match.id


def _build_bye_rounds_single_elim(
    participants: list[Participant],
    bye_rounds: dict[int, int],
    third_place_match: bool,
) -> Bracket:
    """Build a single-elim tree bottom-up from an explicit per-seed bye configuration.

    Round 1 pairs the participants with zero byes. Round ``r`` pairs the winners carried over
    from round ``r - 1`` with the participants whose bye count is exactly ``r - 1`` (they enter
    here for the first time). Entering seeds, being better-ranked than any climber, are folded
    against the carried winners (strongest vs weakest) so the top seeds stay apart. A round
    whose participant count is odd is structurally impossible and raises ``ValidationError``.
    """
    ordered = sorted(participants, key=lambda p: p.seed)
    byes_of = _validate_bye_rounds(ordered, bye_rounds)
    max_bye = max(byes_of.values())

    entering_by_round: dict[int, list[Participant]] = {}
    for p in ordered:  # ascending seed keeps each entering list strongest-first
        entering_by_round.setdefault(byes_of[p.seed], []).append(p)

    id_gen = IdGen()
    matches: list[Match] = []
    by_id: dict[int, Match] = {}
    carries: list[int] = []  # match ids whose winners advance into the next round
    round_number = 0

    while True:
        round_number += 1
        entering = entering_by_round.get(round_number - 1, [])
        incoming: list[_Incoming] = [("seed", p) for p in entering]
        incoming += [("feeder", mid) for mid in carries]
        total = len(incoming)

        if total == 0:
            raise ValidationError(
                f"bye_rounds is invalid: round {round_number} has no participants."
            )
        if total % 2 != 0:
            raise ValidationError(
                f"bye_rounds is invalid: round {round_number} would have {total} active "
                "participants, which cannot be paired evenly. Adjust the bye counts so every "
                "round has an even number of players (a seed may have at most one more bye "
                "than the seed below it)."
            )

        # Fold strongest against weakest: incoming[i] meets incoming[n-1-i].
        new_carries: list[int] = []
        for i in range(total // 2):
            m = make_match(id_gen(), round_number, BracketSide.WINNERS)
            _attach_incoming(m, incoming[i], by_id)
            _attach_incoming(m, incoming[total - 1 - i], by_id)
            matches.append(m)
            by_id[m.id] = m
            new_carries.append(m.id)
        carries = new_carries

        if len(carries) == 1 and (round_number - 1) >= max_bye:
            break
        if round_number > len(ordered) + 1:  # safety: should be unreachable once validated
            raise ValidationError("bye_rounds does not resolve to a single champion.")

    total_rounds = round_number
    final_id = carries[0]

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
        config={"third_place_match": third_place_match, "bye_rounds": dict(byes_of)},
    )
    settle_initial(bracket)
    return bracket
