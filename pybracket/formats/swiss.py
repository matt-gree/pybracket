from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from ..advancement.engine import settle_initial
from ..errors import BracketStateError, SwissRoundIncompleteError
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState, MatchStatus, PairingMethod
from ..models.match import Match
from ..models.participant import Participant
from ..models.round import Round
from ..naming.round_names import swiss_round_name
from ..pairing.dutch import dutch_pairings
from ..pairing.monrad import monrad_pairings
from ..tiebreakers.base import StandingsContext, Tiebreaker
from ..tiebreakers.buchholz import BuchholzTiebreaker
from ..tiebreakers.head_to_head import HeadToHeadTiebreaker
from ..tiebreakers.standings import serialize_tiebreakers
from ..tiebreakers.win_count import WinCountTiebreaker
from ..utils.math import recommend_swiss_rounds
from ..utils.validation import validate_participants
from .base import IdGen, make_match

__all__ = ["generate_swiss", "advance_swiss_round"]


def _default_swiss_tiebreakers() -> list[Tiebreaker]:
    return [WinCountTiebreaker(), BuchholzTiebreaker(), HeadToHeadTiebreaker()]


PairingFn = Callable[
    [list[Participant], dict[Any, float], set[frozenset[Any]], set[Any], bool],
    tuple[list[tuple[Any, Any]], Any],
]


def _pairing_fn(method: PairingMethod) -> PairingFn:
    return dutch_pairings if method is PairingMethod.DUTCH else monrad_pairings


def _played_pairs(matches: list[Match]) -> set[frozenset[Any]]:
    pairs: set[frozenset[Any]] = set()
    for m in matches:
        if m.participant1_id is not None and m.participant2_id is not None:
            pairs.add(frozenset((m.participant1_id, m.participant2_id)))
    return pairs


def _bye_recipients(matches: list[Match]) -> set[Any]:
    return {
        m.winner_id
        for m in matches
        if m.status is MatchStatus.BYE and m.winner_id is not None
    }


def _build_round(
    matches: list[Match],
    rounds: list[Round],
    id_gen: IdGen,
    round_number: int,
    pairings: list[tuple[Any, Any]],
    bye_id: Any | None,
    total_rounds: int,
) -> None:
    match_ids: list[int] = []
    for a, b in pairings:
        m = make_match(id_gen(), round_number, BracketSide.WINNERS, a, b)
        matches.append(m)
        match_ids.append(m.id)
    if bye_id is not None:
        m = make_match(id_gen(), round_number, BracketSide.WINNERS, bye_id, None)
        matches.append(m)
        match_ids.append(m.id)
    rounds.append(
        Round(
            number=round_number,
            bracket_side=BracketSide.WINNERS,
            match_ids=match_ids,
            name=swiss_round_name(round_number, total_rounds),
        )
    )


def generate_swiss(
    participants: list[Participant],
    rounds: int | None = None,
    pairing_method: PairingMethod = PairingMethod.DUTCH,
    tiebreakers: list[Tiebreaker] | None = None,
    allow_bye: bool = True,
) -> Bracket:
    """Generate a Swiss bracket and pair the first round (later rounds via advance_swiss_round)."""
    validate_participants(participants)
    total_rounds = rounds if rounds is not None else recommend_swiss_rounds(len(participants))
    tb = tiebreakers if tiebreakers is not None else _default_swiss_tiebreakers()

    config: dict[str, Any] = {
        "rounds": total_rounds,
        "pairing_method": pairing_method,
        "tiebreakers": serialize_tiebreakers(tb),
        "allow_bye": allow_bye,
    }

    scores = {p.id: 0.0 for p in participants}
    pair_fn = _pairing_fn(pairing_method)
    pairings, bye_id = pair_fn(participants, scores, set(), set(), allow_bye)

    id_gen = IdGen()
    matches: list[Match] = []
    round_list: list[Round] = []
    _build_round(matches, round_list, id_gen, 1, pairings, bye_id, total_rounds)

    bracket = Bracket(
        format="swiss",
        state=BracketState.PUBLISHED,
        participants=list(participants),
        matches=matches,
        rounds=round_list,
        config=config,
    )
    settle_initial(bracket)
    return bracket


def advance_swiss_round(bracket: Bracket) -> Bracket:
    """Generate the next Swiss round's pairings. Raises if the current round is incomplete."""
    if bracket.format != "swiss":
        raise BracketStateError("advance_swiss_round() requires a Swiss bracket.")
    if bracket.state is BracketState.DRAFT:
        raise BracketStateError("Start the tournament before reporting results.")

    total_rounds = int(bracket.config["rounds"])
    current_round = max((m.round_number for m in bracket.matches), default=0)

    incomplete = [
        m
        for m in bracket.matches
        if m.round_number == current_round
        and m.status not in (MatchStatus.COMPLETED, MatchStatus.BYE)
    ]
    if incomplete:
        raise SwissRoundIncompleteError(
            f"Round {current_round} is not complete; cannot pair the next round."
        )
    if current_round >= total_rounds:
        raise BracketStateError("All Swiss rounds have already been generated.")

    b = copy.deepcopy(bracket)
    ids = [p.id for p in b.participants]
    ctx = StandingsContext(b.matches, ids)
    scores = {pid: float(ctx.wins[pid]) for pid in ids}

    method = PairingMethod(b.config["pairing_method"]) if isinstance(
        b.config["pairing_method"], str
    ) else b.config["pairing_method"]
    pair_fn = _pairing_fn(method)
    pairings, bye_id = pair_fn(
        b.participants,
        scores,
        _played_pairs(b.matches),
        _bye_recipients(b.matches),
        bool(b.config.get("allow_bye", True)),
    )

    next_id = max(m.id for m in b.matches) + 1
    id_gen = IdGen(start=next_id)
    _build_round(
        b.matches, b.rounds, id_gen, current_round + 1, pairings, bye_id, total_rounds
    )
    settle_initial(b)
    return b
