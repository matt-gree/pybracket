from __future__ import annotations

from typing import Literal

from ..advancement.engine import settle_initial
from ..errors import ValidationError
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState, MatchStatus
from ..models.match import Match
from ..models.participant import Participant
from ..models.round import Round
from ..naming.round_names import gauntlet_round_name
from ..seeding.algorithms import seed_slots
from ..utils.math import next_power_of_2
from ..utils.validation import validate_participants
from .base import IdGen, build_standard_bracket, make_match

__all__ = ["generate_gauntlet", "refresh_gauntlet_choices"]

# A survivor source: where a dual-gauntlet semifinal's challenger comes from.
#   ("feeder", match_id)  -> winner of a lower-seed sub-bracket match
#   ("concrete", pid)     -> a lone lower seed (no sub-bracket match needed)
#   ("bye", None)              -> no opponent; the top seed byes straight to the final
Survivor = tuple[str, object]


def _build_single_gauntlet(participants: list[Participant]) -> Bracket:
    """Linear ladder: the two lowest seeds play, the winner climbs to face each higher seed."""
    ordered = sorted(participants, key=lambda p: p.seed)  # ordered[0] = seed 1
    n = len(ordered)
    id_gen = IdGen()
    matches: list[Match] = []
    rounds: list[Round] = []
    total_rounds = n - 1

    # Round 1: the two lowest seeds.
    m1 = make_match(id_gen(), 1, BracketSide.WINNERS, ordered[n - 1].id, ordered[n - 2].id)
    matches.append(m1)
    rounds.append(
        Round(1, BracketSide.WINNERS, [m1.id], gauntlet_round_name(1, total_rounds, "single"))
    )

    prev = m1
    for k in range(2, n):
        challenger = ordered[n - 1 - k]  # seed (N - k); seed 1 enters only at the final
        m = make_match(id_gen(), k, BracketSide.WINNERS, None, challenger.id)
        matches.append(m)
        prev.next_winner_match_id = m.id
        rounds.append(
            Round(k, BracketSide.WINNERS, [m.id], gauntlet_round_name(k, total_rounds, "single"))
        )
        prev = m

    bracket = Bracket(
        format="gauntlet",
        state=BracketState.PUBLISHED,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config={"style": "single", "opponent_choice": False, "choice_scope": "round"},
    )
    settle_initial(bracket)
    return bracket


def _build_dual_gauntlet(
    participants: list[Participant],
    opponent_choice: bool,
    choice_scope: str,
) -> Bracket:
    """Seeds 1 and 2 are byed to the two semifinals; seeds 3..N play down to two survivors.

    With `opponent_choice`, the higher seed (1) picks which survivor to face in the
    semifinal and seed 2 takes the other.
    """
    ordered = sorted(participants, key=lambda p: p.seed)
    seed1, seed2 = ordered[0], ordered[1]
    lower = ordered[2:]
    id_gen = IdGen()
    matches: list[Match] = []
    rounds: list[Round] = []

    if not lower:
        # Only two participants: a single final.
        final = make_match(id_gen(), 1, BracketSide.WINNERS, seed1.id, seed2.id)
        matches.append(final)
        rounds.append(Round(1, BracketSide.WINNERS, [final.id], "Final"))
        return _finalize_dual(participants, matches, rounds, opponent_choice, choice_scope)

    surv_a, surv_b, sub_matches, sub_round_ids, semi_round = _build_lower_subbracket(lower, id_gen)
    matches.extend(sub_matches)
    by_id = {m.id: m for m in matches}

    for i, ids in enumerate(sub_round_ids):
        rounds.append(
            Round(i + 1, BracketSide.WINNERS, list(ids), f"Gauntlet Round {i + 1}")
        )

    final_round = semi_round + 1
    sf1 = make_match(id_gen(), semi_round, BracketSide.WINNERS, seed1.id, _concrete(surv_a))
    sf2 = make_match(id_gen(), semi_round, BracketSide.WINNERS, seed2.id, _concrete(surv_b))
    final = make_match(id_gen(), final_round, BracketSide.WINNERS)
    sf1.next_winner_match_id = final.id
    sf2.next_winner_match_id = final.id
    _wire_survivor(surv_a, sf1, by_id)
    _wire_survivor(surv_b, sf2, by_id)

    # Opponent choice only makes sense when both semifinals have a real survivor to choose.
    if opponent_choice and surv_a[0] != "bye" and surv_b[0] != "bye":
        sf1.metadata = {"gauntlet_role": "chooser", "choice_other_match": sf2.id}
        sf2.metadata = {"gauntlet_role": "other"}

    matches.extend([sf1, sf2, final])
    rounds.append(Round(semi_round, BracketSide.WINNERS, [sf1.id, sf2.id], "Semifinals"))
    rounds.append(Round(final_round, BracketSide.WINNERS, [final.id], "Final"))

    return _finalize_dual(participants, matches, rounds, opponent_choice, choice_scope)


def _build_lower_subbracket(
    lower: list[Participant], id_gen: IdGen
) -> tuple[Survivor, Survivor, list[Match], list[list[int]], int]:
    """Reduce the lower seeds to two survivors (the two halves of a single-elim sub-bracket)."""
    if len(lower) == 1:
        return ("concrete", lower[0].id), ("bye", None), [], [], 1
    if len(lower) == 2:
        return ("concrete", lower[0].id), ("concrete", lower[1].id), [], [], 1

    size = next_power_of_2(len(lower))
    slots = seed_slots(lower, size)
    sub_matches, round_ids, final_id = build_standard_bracket(slots, id_gen, BracketSide.WINNERS)
    depth = len(round_ids)
    # The two matches feeding the sub-bracket final become the two survivors; the sub-final
    # itself is replaced by the dual-gauntlet semifinals (which inject seeds 1 and 2).
    feeders = [m for m in sub_matches if m.next_winner_match_id == final_id]
    left, right = feeders[0], feeders[1]
    kept = [m for m in sub_matches if m.id != final_id]
    left.next_winner_match_id = None
    right.next_winner_match_id = None
    return ("feeder", left.id), ("feeder", right.id), kept, round_ids[:-1], depth


def _concrete(surv: Survivor) -> object | None:
    return surv[1] if surv[0] == "concrete" else None


def _wire_survivor(surv: Survivor, semifinal: Match, by_id: dict[int, Match]) -> None:
    if surv[0] == "feeder":
        by_id[surv[1]].next_winner_match_id = semifinal.id  # type: ignore[index]


def _finalize_dual(
    participants: list[Participant],
    matches: list[Match],
    rounds: list[Round],
    opponent_choice: bool,
    choice_scope: str,
) -> Bracket:
    bracket = Bracket(
        format="gauntlet",
        state=BracketState.PUBLISHED,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config={
            "style": "dual",
            "opponent_choice": opponent_choice,
            "choice_scope": choice_scope,
        },
    )
    settle_initial(bracket)
    if opponent_choice:
        refresh_gauntlet_choices(bracket)
    return bracket


def generate_gauntlet(
    participants: list[Participant],
    style: Literal["single", "dual"],
    opponent_choice: bool = False,
    choice_scope: Literal["round", "semifinals"] = "round",
) -> Bracket:
    """Generate a single-sided (linear chain) or dual-sided (two-bracket) gauntlet."""
    validate_participants(participants)
    if style == "single":
        if opponent_choice:
            # A single gauntlet is a fixed ladder: the next opponent is always the next seed
            # down, so there is nothing to choose. Opponent choice only applies to dual.
            raise ValidationError(
                "opponent_choice is only supported for dual-sided gauntlets; a single-sided "
                "gauntlet is a fixed ladder with no opponent to choose."
            )
        return _build_single_gauntlet(participants)
    if style == "dual":
        return _build_dual_gauntlet(participants, opponent_choice, choice_scope)
    raise ValidationError(f"Unknown gauntlet style: {style!r}")


def refresh_gauntlet_choices(bracket: Bracket) -> None:
    """Expose the dual-gauntlet semifinal choice once both lower-bracket survivors are known.

    The higher seed's semifinal becomes PENDING_CHOICE with both survivors in `choice_pool`;
    `report_choice` then assigns the chosen survivor to seed 1 and the other to seed 2.
    """
    if bracket.format != "gauntlet" or not bracket.config.get("opponent_choice"):
        return
    if bracket.config.get("style") != "dual":
        return

    chooser = next(
        (m for m in bracket.matches if m.metadata.get("gauntlet_role") == "chooser"), None
    )
    if chooser is None or chooser.metadata.get("choice_made"):
        return
    other = next(
        (m for m in bracket.matches if m.id == chooser.metadata.get("choice_other_match")), None
    )
    if other is None:
        return
    if chooser.status is MatchStatus.COMPLETED or other.status is MatchStatus.COMPLETED:
        return

    surv_chooser = chooser.participant2_id  # seed sits in slot 1, survivor arrives in slot 2
    surv_other = other.participant2_id
    if surv_chooser is None or surv_other is None:
        # Hold a semifinal that is already filled until the other survivor is decided.
        for sf in (chooser, other):
            if (
                sf.participant1_id is not None
                and sf.participant2_id is not None
                and sf.status is MatchStatus.READY
            ):
                sf.status = MatchStatus.PENDING
        return

    chooser.metadata = {**chooser.metadata, "choice_pool": [surv_chooser, surv_other]}
    chooser.status = MatchStatus.PENDING_CHOICE
    other.status = MatchStatus.PENDING
