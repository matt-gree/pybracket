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
from ..models.standing import Standing
from ..naming.round_names import matchweek_round_name
from ..seeding.pool_seeding import snake_pool_assignment
from ..tiebreakers.base import Tiebreaker
from ..tiebreakers.standings import get_standings, serialize_tiebreakers
from ..utils.validation import validate_participants
from .base import IdGen, make_match
from .round_robin import circle_method_rounds

__all__ = ["generate_league", "league_divisions", "division_standings"]


def generate_league(
    participants: list[Participant],
    *,
    divisions: int = 1,
    best_of: int = 1,
    points: PointsSystem | None = None,
    tiebreakers: list[Tiebreaker] | None = None,
    schedule: str = "circle",
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """Generate a league: one or more divisions each playing a full single round-robin season.

    With ``divisions=1`` it is a single league table. With ``divisions>1`` teams are snake-seeded
    into divisions, each division plays a full intra-division round-robin, and the divisions run
    in parallel matchweeks (cross-division play is layered on separately). Everything lives in
    **one** bracket; per-division tables come from :func:`division_standings`, the overall table
    from ``get_standings``.

    Each match carries schedule metadata the engine never reads (``matchweek``, ``home_id``,
    ``away_id``, ``division``); the TO may edit it freely. Standings rank by record, or by points
    when a ``PointsSystem`` is given. An even ``best_of`` requires a draws-enabled points system.
    """
    validate_participants(participants)
    if schedule not in ("circle", "manual"):
        raise ValidationError("schedule must be 'circle' or 'manual'.")
    if divisions < 1:
        raise ValidationError("divisions must be a positive integer.")
    if divisions > len(participants) // 2:
        raise ValidationError("Each division needs at least two teams.")
    if best_of < 1:
        raise ValidationError("best_of must be a positive integer.")
    if best_of % 2 == 0 and (points is None or not points.draws_allowed):
        raise ValidationError(
            "An even best_of needs a PointsSystem(draws_allowed=True) (a level series draws)."
        )

    rosters = snake_pool_assignment(participants, divisions)
    division_rounds = [circle_method_rounds([p.id for p in roster]) for roster in rosters]
    total = max((len(dr) for dr in division_rounds), default=0)

    id_gen = IdGen()
    # Greedy home/away balancing: each game is hosted by whichever team has hosted fewer so far.
    home_counts: dict[Any, int] = {p.id: 0 for p in participants}
    matches: list[Match] = []
    rounds: list[Round] = []

    for week_index in range(total):
        week = week_index + 1
        match_ids: list[int] = []
        for division, rounds_for_div in enumerate(division_rounds):
            if week_index >= len(rounds_for_div):
                continue  # this (smaller) division has already finished its season
            for position, (a, b) in enumerate(rounds_for_div[week_index]):
                if a is None or b is None:
                    continue  # the resting team this matchweek (odd division)
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
                    metadata={
                        "matchweek": week,
                        "home_id": home,
                        "away_id": away,
                        "division": division,
                    },
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

    config: dict[str, Any] = {
        "double": False,
        "best_of": best_of,
        "divisions": [[p.id for p in roster] for roster in rosters],
    }
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


def league_divisions(bracket: Bracket) -> list[list[Any]]:
    """The roster (participant ids) of each division, in division order."""
    rosters = bracket.config.get("divisions")
    if rosters:
        return [list(r) for r in rosters]
    return [[p.id for p in bracket.participants]]


def division_standings(bracket: Bracket, division: int) -> list[Standing]:
    """The standings table for one division (its teams ranked by their full record)."""
    rosters = league_divisions(bracket)
    if not 0 <= division < len(rosters):
        raise ValidationError(f"No division {division} (league has {len(rosters)}).")
    return get_standings(bracket, rosters[division])
