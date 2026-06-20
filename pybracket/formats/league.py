from __future__ import annotations

from typing import Any

from ..advancement.engine import settle_initial
from ..errors import ValidationError
from ..models.bracket import Bracket
from ..models.enums import BracketSide, BracketState
from ..models.match import Match
from ..models.participant import Participant
from ..models.points import PointsSystem
from ..models.round import Round
from ..naming.round_names import matchweek_round_name
from ..tiebreakers.base import Tiebreaker
from ..tiebreakers.standings import serialize_tiebreakers
from ..utils.validation import validate_participants
from .base import IdGen, make_match
from .round_robin import circle_method_rounds

__all__ = ["generate_league"]


def generate_league(
    participants: list[Participant],
    *,
    best_of: int = 1,
    points: PointsSystem | None = None,
    tiebreakers: list[Tiebreaker] | None = None,
    schedule: str = "circle",
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """Generate a single-division league: a fully-scheduled single round-robin season.

    Every pairing is played once across a series of **matchweeks** (one per round). Each match
    carries schedule metadata the engine never reads (``matchweek``, ``home_id``, ``away_id``);
    the TO may edit it freely. Standings rank by record, or by points when a ``PointsSystem`` is
    given. An even ``best_of`` (a series that can end level) requires a points system that allows
    draws. Divisions, cross-division play and home/away double rounds are layered on later.
    """
    validate_participants(participants)
    if schedule not in ("circle", "manual"):
        raise ValidationError("schedule must be 'circle' or 'manual'.")
    if best_of < 1:
        raise ValidationError("best_of must be a positive integer.")
    if best_of % 2 == 0 and (points is None or not points.draws_allowed):
        raise ValidationError(
            "An even best_of needs a PointsSystem(draws_allowed=True) (a level series draws)."
        )

    id_gen = IdGen()
    pairings_by_round = circle_method_rounds([p.id for p in participants])
    total = len(pairings_by_round)

    # Greedy home/away balancing: each game is hosted by whichever team has hosted fewer so far,
    # so every team ends up with a near-even home/away split (best-effort; no streak constraint).
    home_counts: dict[Any, int] = {p.id: 0 for p in participants}

    matches: list[Match] = []
    rounds: list[Round] = []
    for r_index, pairings in enumerate(pairings_by_round):
        week = r_index + 1
        match_ids: list[int] = []
        for position, (a, b) in enumerate(pairings):
            if a is None or b is None:
                continue  # the resting team this matchweek (odd field)
            if home_counts[a] < home_counts[b] or (
                home_counts[a] == home_counts[b] and (week + position) % 2 == 0
            ):
                home, away = a, b
            else:
                home, away = b, a
            home_counts[home] += 1
            m = make_match(
                id_gen(),
                week,
                BracketSide.WINNERS,
                participant1_id=a,
                participant2_id=b,
                metadata={"matchweek": week, "home_id": home, "away_id": away},
            )
            m.best_of = best_of
            matches.append(m)
            match_ids.append(m.id)
        rounds.append(
            Round(
                number=week,
                bracket_side=BracketSide.WINNERS,
                match_ids=match_ids,
                name=matchweek_round_name(week, total),
                best_of=best_of if best_of > 1 else None,
            )
        )

    config: dict[str, Any] = {"double": False, "best_of": best_of}
    if tiebreakers is not None:
        config["tiebreakers"] = serialize_tiebreakers(tiebreakers)
    if points is not None:
        config["points_system"] = points

    bracket = Bracket(
        format="league",
        state=state,
        participants=list(participants),
        matches=matches,
        rounds=rounds,
        config=config,
    )
    settle_initial(bracket)
    return bracket
