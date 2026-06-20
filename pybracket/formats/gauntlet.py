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
from ..utils.validation import validate_participants
from .base import IdGen, make_match

__all__ = ["generate_gauntlet", "refresh_gauntlet_choices", "refresh_gauntlet_round_choices"]


def _build_single_gauntlet(
    participants: list[Participant], state: BracketState = BracketState.PUBLISHED
) -> Bracket:
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
        state=state,
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
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """Seeds 1 and 2 are seated at the two semifinals; everyone below climbs two ladders.

    The lower seeds form a "staircase": two seats are filled at every level (the two best seeds
    not yet placed), each meeting a challenger climbing from the level below. This keeps exactly
    two games per round at every size — a true double gauntlet that never collapses into a
    regular sub-bracket the way a balanced lower bracket does past ~8 players.

    ``opponent_choice`` lets the higher seat of a level pick which climber to face; the other
    seat inherits the rest. With ``choice_scope="round"`` that choice is offered at every level;
    with ``"semifinals"`` only seeds 1 and 2 choose (the lower levels are fixed by seeding).
    """
    ordered = sorted(participants, key=lambda p: p.seed)
    if len(ordered) <= 3:
        return _build_dual_small(ordered, participants, opponent_choice, choice_scope, state)
    return _build_dual_staircase(ordered, participants, opponent_choice, choice_scope, state)


def _build_dual_small(
    ordered: list[Participant],
    participants: list[Participant],
    opponent_choice: bool,
    choice_scope: str,
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """The 2- and 3-player shapes: a single final, or one byed semifinalist."""
    id_gen = IdGen()
    if len(ordered) == 2:
        final = make_match(id_gen(), 1, BracketSide.WINNERS, ordered[0].id, ordered[1].id)
        rounds = [Round(1, BracketSide.WINNERS, [final.id], "Final")]
        return _finalize_dual(participants, [final], rounds, opponent_choice, choice_scope, state)

    # Three players: seed 1 faces seed 3 at one semifinal; seed 2 byes into the final.
    sf1 = make_match(id_gen(), 1, BracketSide.WINNERS, ordered[0].id, ordered[2].id)
    sf2 = make_match(id_gen(), 1, BracketSide.WINNERS, ordered[1].id, None)
    final = make_match(id_gen(), 2, BracketSide.WINNERS)
    sf1.next_winner_match_id = final.id
    sf2.next_winner_match_id = final.id
    rounds = [
        Round(1, BracketSide.WINNERS, [sf1.id, sf2.id], "Semifinals"),
        Round(2, BracketSide.WINNERS, [final.id], "Final"),
    ]
    return _finalize_dual(
        participants, [sf1, sf2, final], rounds, opponent_choice, choice_scope, state
    )


def _level_has_choice(level: int, opponent_choice: bool, choice_scope: str) -> bool:
    """Whether the higher seat at a seated level chooses its challenger (level 1 == semifinals)."""
    if not opponent_choice:
        return False
    if choice_scope == "round":
        return True
    return level == 1  # semifinals scope: only seeds 1 and 2 choose


def _build_dual_staircase(
    ordered: list[Participant],
    participants: list[Participant],
    opponent_choice: bool,
    choice_scope: str,
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """Build the two-ladder staircase for a field of four or more.

    Two seeds are seated at every level (the two best not yet in the ladder), each facing a
    challenger from the level below; their winners become the next level's challengers. Seeds 1
    and 2 are seated at the semifinals, whose winners meet in the final. An odd field gives the
    two lowest seeds a play-in so the bottom level still has exactly two challengers.
    """
    n = len(ordered)
    id_gen = IdGen()
    matches: list[Match] = []
    by_id: dict[int, Match] = {}
    round_no = 0

    odd = n % 2 == 1
    # Seated choice levels (each seats two seeds), counted from the semifinals (level 1) down.
    levels = (n - 3) // 2 if odd else n // 2 - 1

    # --- bottom challengers: the two inputs to the lowest seated level ---
    if odd:
        round_no += 1
        play_in = make_match(
            id_gen(), round_no, BracketSide.WINNERS, ordered[n - 1].id, ordered[n - 2].id
        )
        matches.append(play_in)
        by_id[play_in.id] = play_in
        challengers: list[_Challenger] = [("feeder", play_in.id), ("seed", ordered[n - 3])]
    else:
        challengers = [("seed", ordered[n - 1]), ("seed", ordered[n - 2])]

    # --- seated levels, bottom (level `levels`) up to the semifinals (level 1) ---
    for level in range(levels, 0, -1):
        round_no += 1
        seat_high = ordered[2 * level - 2]  # the better seed of the pair
        seat_low = ordered[2 * level - 1]
        high_match = make_match(id_gen(), round_no, BracketSide.WINNERS, seat_high.id, None)
        low_match = make_match(id_gen(), round_no, BracketSide.WINNERS, seat_low.id, None)
        _attach_challenger(high_match, challengers[0], by_id)
        _attach_challenger(low_match, challengers[1], by_id)
        if _level_has_choice(level, opponent_choice, choice_scope):
            high_match.metadata = {"gauntlet_role": "chooser", "choice_other_match": low_match.id}
            low_match.metadata = {"gauntlet_role": "other"}
        for match in (high_match, low_match):
            matches.append(match)
            by_id[match.id] = match
        # This level's two winners are the next level's challengers (one ladder per seat).
        challengers = [("feeder", high_match.id), ("feeder", low_match.id)]

    # --- final: the two semifinal winners meet ---
    round_no += 1
    final = make_match(id_gen(), round_no, BracketSide.WINNERS)
    _attach_challenger(final, challengers[0], by_id)
    _attach_challenger(final, challengers[1], by_id)
    matches.append(final)
    by_id[final.id] = final

    total_rounds = round_no
    rounds = [
        Round(
            number=rn,
            bracket_side=BracketSide.WINNERS,
            match_ids=[m.id for m in matches if m.round_number == rn],
            name=gauntlet_round_name(rn, total_rounds, "dual"),
        )
        for rn in range(1, total_rounds + 1)
    ]
    return _finalize_dual(participants, matches, rounds, opponent_choice, choice_scope, state)


def _finalize_dual(
    participants: list[Participant],
    matches: list[Match],
    rounds: list[Round],
    opponent_choice: bool,
    choice_scope: str,
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    bracket = Bracket(
        format="gauntlet",
        state=state,
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
        if choice_scope == "round":
            refresh_gauntlet_round_choices(bracket)
        else:
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


def generate_gauntlet(
    participants: list[Participant],
    style: Literal["single", "dual"],
    opponent_choice: bool = False,
    choice_scope: Literal["round", "semifinals"] = "round",
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """Generate a single-sided (linear chain) or dual-sided (two-ladder) gauntlet.

    Pass ``state=BracketState.DRAFT`` to build the ladder without locking it for play, so a
    tournament phase can review/reseed before ``publish_phase``.
    """
    validate_participants(participants)
    if style == "single":
        if opponent_choice:
            # A single gauntlet is a fixed ladder: the next opponent is always the next seed
            # down, so there is nothing to choose. Opponent choice only applies to dual.
            raise ValidationError(
                "opponent_choice is only supported for dual-sided gauntlets; a single-sided "
                "gauntlet is a fixed ladder with no opponent to choose."
            )
        return _build_single_gauntlet(participants, state)
    if style == "dual":
        return _build_dual_gauntlet(participants, opponent_choice, choice_scope, state)
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
