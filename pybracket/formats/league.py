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


def _division_schedule(
    ids: list[Any], double: bool, home_counts: dict[Any, int]
) -> list[list[tuple[Any, Any]]]:
    """One division's schedule: a list of matchweeks, each a list of ``(home_id, away_id)``.

    The first leg assigns venues greedily (each game hosted by whichever team has hosted fewer
    so far). A double round-robin appends a mirrored second leg with venues swapped, which makes
    every team's home/away split exactly even (it hosts each opponent once).
    """
    leg1: list[list[tuple[Any, Any]]] = []
    for r_index, pairings in enumerate(circle_method_rounds(ids)):
        fixtures: list[tuple[Any, Any]] = []
        for position, (a, b) in enumerate(pairings):
            if a is None or b is None:
                continue  # the resting team this matchweek (odd field)
            if home_counts[a] < home_counts[b] or (
                home_counts[a] == home_counts[b] and (r_index + position) % 2 == 0
            ):
                home, away = a, b
            else:
                home, away = b, a
            home_counts[home] += 1
            fixtures.append((home, away))
        leg1.append(fixtures)
    if not double:
        return leg1
    leg2 = [[(away, home) for home, away in week] for week in leg1]
    return leg1 + leg2


def generate_league(
    participants: list[Participant],
    *,
    divisions: int = 1,
    double: bool = False,
    best_of: int = 1,
    points: PointsSystem | None = None,
    tiebreakers: list[Tiebreaker] | None = None,
    schedule: str = "circle",
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """Generate a league: one or more divisions each playing a full intra-division round-robin.

    With ``divisions=1`` it is a single league table. With ``divisions>1`` teams are snake-seeded
    into divisions, each division plays a full intra-division round-robin, and the divisions run
    in parallel matchweeks (cross-division play is layered on separately). Everything lives in
    **one** bracket; per-division tables come from :func:`division_standings`, the overall table
    from ``get_standings``. ``double=True`` is a home/away double round-robin (every pairing twice
    with venues swapped, a mirrored second half).

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
    home_counts: dict[Any, int] = {p.id: 0 for p in participants}
    division_schedules = [
        _division_schedule([p.id for p in roster], double, home_counts) for roster in rosters
    ]
    total = max((len(s) for s in division_schedules), default=0)

    id_gen = IdGen()
    matches: list[Match] = []
    rounds: list[Round] = []
    for week_index in range(total):
        week = week_index + 1
        match_ids: list[int] = []
        for division, sched in enumerate(division_schedules):
            if week_index >= len(sched):
                continue  # this (smaller) division has already finished its season
            for home, away in sched[week_index]:
                m = make_match(
                    id_gen(),
                    week,
                    BracketSide.WINNERS,
                    participant1_id=home,
                    participant2_id=away,
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
        "double": double,
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
