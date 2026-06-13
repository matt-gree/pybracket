from __future__ import annotations

from typing import Any, Literal

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

__all__ = ["generate_gauntlet", "refresh_gauntlet_choices", "refresh_gauntlet_round_choices"]

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


# A challenger entering a seated player's match: a lone seed, or the winner of a feeder match.
_Challenger = tuple[str, Any]  # ("seed", Participant) | ("feeder", match_id)


def _attach_challenger(match: Match, challenger: _Challenger, by_id: dict[int, Match]) -> None:
    """Place a seed challenger into the match's open slot, or wire a feeder's winner toward it."""
    kind, value = challenger
    if kind == "seed":
        if match.participant1_id is None:
            match.participant1_id = value.id
        else:
            match.participant2_id = value.id
    else:  # feeder match id
        by_id[value].next_winner_match_id = match.id


def _build_dual_gauntlet_round(participants: list[Participant]) -> Bracket:
    """Build a round-by-round-choice dual gauntlet as a two-wide "staircase" tree.

    Two seeds are *seated* at every level (the two best seeds not yet in the ladder). Each
    faces a *challenger* climbing from the level below; the higher-seeded of the pair chooses
    which challenger to take and the other inherits the rest. Seeds 1 and 2 are seated at the
    semifinals, whose winners meet in the final — the same finish as the semifinals-scope dual
    gauntlet. For an odd field the two lowest seeds contest a play-in so the bottom level still
    has exactly two challengers; an even field feeds the two lowest seeds in directly.
    """
    ordered = sorted(participants, key=lambda p: p.seed)
    n = len(ordered)
    if n <= 3:
        # Too few players to choose round by round; the standard dual gauntlet already covers
        # the 2- and 3-player shapes (a single final / one byed semifinalist).
        return _build_dual_gauntlet(participants, opponent_choice=True, choice_scope="round")

    id_gen = IdGen()
    matches: list[Match] = []
    by_id: dict[int, Match] = {}
    round_no = 0

    odd = n % 2 == 1
    # Number of seated choice levels (each seats two seeds), from the semifinals down.
    levels = (n - 3) // 2 if odd else n // 2 - 1

    # --- bottom challengers: the two inputs to the lowest seated level ---
    if odd:
        round_no += 1
        play_in = make_match(
            id_gen(), round_no, BracketSide.WINNERS, ordered[n - 1].id, ordered[n - 2].id
        )
        matches.append(play_in)
        by_id[play_in.id] = play_in
        # Challenger A = winner of the play-in; challenger B = the next seed up (enters directly).
        challengers: list[_Challenger] = [("feeder", play_in.id), ("seed", ordered[n - 3])]
    else:
        challengers = [("seed", ordered[n - 1]), ("seed", ordered[n - 2])]

    # --- seated levels, bottom (level `levels`) up to the semifinals (level 1) ---
    for level in range(levels, 0, -1):
        round_no += 1
        seat_high = ordered[2 * level - 2]  # better seed -> the chooser
        seat_low = ordered[2 * level - 1]
        chooser = make_match(id_gen(), round_no, BracketSide.WINNERS, seat_high.id, None)
        other = make_match(id_gen(), round_no, BracketSide.WINNERS, seat_low.id, None)
        _attach_challenger(chooser, challengers[0], by_id)
        _attach_challenger(other, challengers[1], by_id)
        chooser.metadata = {"gauntlet_role": "chooser", "choice_other_match": other.id}
        other.metadata = {"gauntlet_role": "other"}
        for match in (chooser, other):
            matches.append(match)
            by_id[match.id] = match
        # This level's two winners are the challengers for the next level up.
        challengers = [("feeder", chooser.id), ("feeder", other.id)]

    # --- final: the two semifinal winners meet ---
    round_no += 1
    final = make_match(id_gen(), round_no, BracketSide.WINNERS)
    _attach_challenger(final, challengers[0], by_id)
    _attach_challenger(final, challengers[1], by_id)
    matches.append(final)
    by_id[final.id] = final

    total_rounds = round_no
    rounds: list[Round] = []
    for rn in range(1, total_rounds + 1):
        ids = [m.id for m in matches if m.round_number == rn]
        rounds.append(
            Round(
                number=rn,
                bracket_side=BracketSide.WINNERS,
                match_ids=ids,
                name=gauntlet_round_name(rn, total_rounds, "dual"),
            )
        )

    bracket = Bracket(
        format="gauntlet",
        state=BracketState.PUBLISHED,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config={"style": "dual", "opponent_choice": True, "choice_scope": "round"},
    )
    settle_initial(bracket)
    refresh_gauntlet_round_choices(bracket)
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
        if opponent_choice and choice_scope == "round":
            return _build_dual_gauntlet_round(participants)
        return _build_dual_gauntlet(participants, opponent_choice, choice_scope)
    raise ValidationError(f"Unknown gauntlet style: {style!r}")


def _open_choice_when_ready(chooser: Match, other: Match) -> None:
    """Open one seated/challenger choice: the chooser becomes PENDING_CHOICE once both of its
    challengers are known, otherwise an already-filled match is held back to PENDING.

    The seated player always sits in slot 1; the challenger arrives in slot 2.
    """
    if chooser.metadata.get("choice_made"):
        return
    if chooser.status is MatchStatus.COMPLETED or other.status is MatchStatus.COMPLETED:
        return

    challenger_chooser = chooser.participant2_id
    challenger_other = other.participant2_id
    if challenger_chooser is None or challenger_other is None:
        # A challenger is no longer known (e.g. a feeder result was unwound). Re-close an
        # offer that was opened but never taken, and hold any filled match back to PENDING
        # until both challengers are known again.
        if chooser.status is MatchStatus.PENDING_CHOICE:
            chooser.status = MatchStatus.PENDING
            chooser.metadata = {
                k: v for k, v in chooser.metadata.items() if k != "choice_pool"
            }
        for match in (chooser, other):
            if (
                match.participant1_id is not None
                and match.participant2_id is not None
                and match.status is MatchStatus.READY
            ):
                match.status = MatchStatus.PENDING
        return

    chooser.metadata = {**chooser.metadata, "choice_pool": [challenger_chooser, challenger_other]}
    chooser.status = MatchStatus.PENDING_CHOICE
    other.status = MatchStatus.PENDING


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
    if chooser is None:
        return
    other = next(
        (m for m in bracket.matches if m.id == chooser.metadata.get("choice_other_match")), None
    )
    if other is None:
        return
    _open_choice_when_ready(chooser, other)


def refresh_gauntlet_round_choices(bracket: Bracket) -> None:
    """Round-scope analogue of :func:`refresh_gauntlet_choices`.

    A round-scope dual gauntlet has a chooser/other pair at *every* level, not only the
    semifinals. After each ``report_result`` this opens whichever chooser now has both of its
    challengers known — choices naturally resolve from the bottom of the ladder up, since each
    level's challengers are the winners of the level below.
    """
    if bracket.format != "gauntlet" or not bracket.config.get("opponent_choice"):
        return
    if bracket.config.get("style") != "dual" or bracket.config.get("choice_scope") != "round":
        return

    for chooser in bracket.matches:
        if chooser.metadata.get("gauntlet_role") != "chooser":
            continue
        other = next(
            (m for m in bracket.matches if m.id == chooser.metadata.get("choice_other_match")),
            None,
        )
        if other is None:
            continue
        _open_choice_when_ready(chooser, other)
