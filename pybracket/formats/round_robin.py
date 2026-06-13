from __future__ import annotations

from typing import Any

from ..advancement.engine import settle_initial
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState
from ..models.match import Match
from ..models.participant import Participant
from ..models.round import Round
from ..naming.round_names import round_robin_round_name
from ..tiebreakers.base import Tiebreaker
from ..tiebreakers.standings import serialize_tiebreakers
from ..utils.validation import validate_participants
from .base import IdGen, make_match

__all__ = ["generate_round_robin", "circle_method_rounds"]


def circle_method_rounds(participant_ids: list[Any]) -> list[list[tuple[Any, Any]]]:
    """Round-robin pairings via the circle method. Odd fields rotate a bye through everyone."""
    players: list[Any] = list(participant_ids)
    if len(players) % 2 == 1:
        players.append(None)  # bye marker
    n = len(players)
    half = n // 2
    rounds: list[list[tuple[Any, Any]]] = []
    for _ in range(n - 1):
        pairings = [(players[i], players[n - 1 - i]) for i in range(half)]
        rounds.append(pairings)
        # Rotate everyone except the first fixed player.
        players = [players[0], players[-1], *players[1:-1]]
    return rounds


def generate_round_robin(
    participants: list[Participant],
    tiebreakers: list[Tiebreaker] | None = None,
    state: BracketState = BracketState.PUBLISHED,
    pool_index: int | None = None,
) -> Bracket:
    """Generate a fully-scheduled round-robin bracket (all pairings created up front)."""
    validate_participants(participants)
    id_gen = IdGen()
    pairings_by_round = circle_method_rounds([p.id for p in participants])

    matches: list[Match] = []
    rounds: list[Round] = []
    total_rounds = len(pairings_by_round)
    for r_index, pairings in enumerate(pairings_by_round):
        match_ids: list[int] = []
        for a, b in pairings:
            if a is None and b is None:
                continue
            m = make_match(
                id_gen(),
                r_index + 1,
                BracketSide.WINNERS,
                participant1_id=a,
                participant2_id=b,
            )
            matches.append(m)
            match_ids.append(m.id)
        name = round_robin_round_name(r_index + 1, total_rounds)
        rounds.append(
            Round(
                number=r_index + 1,
                bracket_side=BracketSide.WINNERS,
                match_ids=match_ids,
                name=name,
            )
        )

    config: dict[str, Any] = {}
    if tiebreakers is not None:
        config["tiebreakers"] = serialize_tiebreakers(tiebreakers)
    if pool_index is not None:
        config["pool_index"] = pool_index

    bracket = Bracket(
        format="round_robin",
        state=state,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config=config,
    )
    settle_initial(bracket)
    return bracket
