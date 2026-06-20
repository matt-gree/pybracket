from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from ..advancement.engine import settle_initial
from ..errors import ValidationError
from ..models.bracket import Bracket
from ..models.cross_division import PAIRINGS, CrossDivision
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

__all__ = [
    "generate_league",
    "league_divisions",
    "division_standings",
    "league_schedule",
    "Matchweek",
    "Fixture",
]


@dataclass(frozen=True)
class Fixture:
    """One scheduled game in a league read-model: who hosts whom, in which division."""

    match_id: int
    home_id: Any
    away_id: Any
    division: int | None  # None for a cross-division game


@dataclass(frozen=True)
class Matchweek:
    number: int
    fixtures: list[Fixture]


def _assign_home(a: Any, b: Any, home_counts: dict[Any, int], parity: int = 0) -> tuple[Any, Any]:
    """Host the game with whichever team has hosted fewer so far (best-effort balance)."""
    if home_counts[a] < home_counts[b] or (home_counts[a] == home_counts[b] and parity % 2 == 0):
        home, away = a, b
    else:
        home, away = b, a
    home_counts[home] += 1
    return home, away


def _division_schedule(
    ids: list[Any], double: bool, home_counts: dict[Any, int]
) -> list[list[tuple[Any, Any]]]:
    """One division's schedule: a list of matchweeks, each a list of ``(home_id, away_id)``.

    The first leg assigns venues greedily. A double round-robin appends a mirrored second leg
    with venues swapped, which makes every team's home/away split exactly even.
    """
    leg1: list[list[tuple[Any, Any]]] = []
    for r_index, pairings in enumerate(circle_method_rounds(ids)):
        fixtures: list[tuple[Any, Any]] = []
        for position, (a, b) in enumerate(pairings):
            if a is None or b is None:
                continue  # the resting team this matchweek (odd field)
            fixtures.append(_assign_home(a, b, home_counts, r_index + position))
        leg1.append(fixtures)
    if not double:
        return leg1
    leg2 = [[(away, home) for home, away in week] for week in leg1]
    return leg1 + leg2


def _cross_pairings(
    rosters: list[list[Any]], cross: CrossDivision, rng: random.Random
) -> list[tuple[Any, Any]]:
    """Distinct inter-division pairings giving each team ~``games_per_team`` opponents (best-effort).

    ``balanced`` prefers same-rank opponents, ``top_seed_favored`` prefers dissimilar ranks (so top
    seeds are steered apart), ``random`` shuffles, ``round_robin`` plays every other-division team.
    """
    division_of: dict[Any, int] = {}
    rank_of: dict[Any, int] = {}
    all_ids: list[Any] = []
    for d, roster in enumerate(rosters):
        for rank, pid in enumerate(roster):
            division_of[pid] = d
            rank_of[pid] = rank
            all_ids.append(pid)

    if cross.pairing == "round_robin":
        return [
            (a, b)
            for i, a in enumerate(all_ids)
            for b in all_ids[i + 1 :]
            if division_of[a] != division_of[b]
        ]

    def preference(pid: Any) -> list[Any]:
        others = [o for o in all_ids if division_of[o] != division_of[pid]]
        if cross.pairing == "balanced":
            others.sort(key=lambda o: (abs(rank_of[o] - rank_of[pid]), division_of[o], rank_of[o]))
        elif cross.pairing == "top_seed_favored":
            others.sort(key=lambda o: (-abs(rank_of[o] - rank_of[pid]), rank_of[o], division_of[o]))
        else:  # random
            rng.shuffle(others)
        return others

    prefs = {pid: preference(pid) for pid in all_ids}
    target = dict.fromkeys(all_ids, cross.games_per_team)
    degree = dict.fromkeys(all_ids, 0)
    used: set[frozenset[Any]] = set()
    pairings: list[tuple[Any, Any]] = []

    while True:
        needy = [pid for pid in all_ids if degree[pid] < target[pid]]
        if not needy:
            break
        needy.sort(key=lambda pid: (-(target[pid] - degree[pid]), rank_of[pid]))
        progressed = False
        for pid in needy:
            opp = next(
                (
                    o
                    for o in prefs[pid]
                    if degree[o] < target[o] and frozenset((pid, o)) not in used
                ),
                None,
            )
            if opp is not None:
                used.add(frozenset((pid, opp)))
                degree[pid] += 1
                degree[opp] += 1
                pairings.append((pid, opp))
                progressed = True
                break
        if not progressed:
            break  # remaining needs are infeasible (best-effort)
    return pairings


def _schedule_into_weeks(
    fixtures: list[tuple[Any, Any]],
) -> list[list[tuple[Any, Any]]]:
    """Greedily colour fixtures into matchweeks so no team plays twice in a week."""
    weeks: list[list[tuple[Any, Any]]] = []
    busy: list[set[Any]] = []
    for home, away in fixtures:
        placed = False
        for w, taken in enumerate(busy):
            if home not in taken and away not in taken:
                weeks[w].append((home, away))
                taken |= {home, away}
                placed = True
                break
        if not placed:
            weeks.append([(home, away)])
            busy.append({home, away})
    return weeks


def generate_league(
    participants: list[Participant],
    *,
    divisions: int = 1,
    double: bool = False,
    best_of: int = 1,
    points: PointsSystem | None = None,
    cross_division: CrossDivision | None = None,
    tiebreakers: list[Tiebreaker] | None = None,
    schedule: str = "circle",
    state: BracketState = BracketState.PUBLISHED,
) -> Bracket:
    """Generate a league: one or more divisions each playing a full intra-division round-robin.

    With ``divisions=1`` it is a single league table. With ``divisions>1`` teams are snake-seeded
    into divisions, each division plays a full intra-division round-robin, and the divisions run
    in parallel matchweeks. ``cross_division`` layers inter-division games on top into extra
    matchweeks. Everything lives in **one** bracket; per-division tables come from
    :func:`division_standings`, the overall table from ``get_standings``. ``double=True`` is a
    home/away double round-robin (every pairing twice with venues swapped).

    Each match carries schedule metadata the engine never reads (``matchweek``, ``home_id``,
    ``away_id``, ``division`` — ``None`` for a cross-division game); the TO may edit it freely.
    Standings rank by record, or by points when a ``PointsSystem`` is given. An even ``best_of``
    requires a draws-enabled points system.
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
    if cross_division is not None:
        if divisions < 2:
            raise ValidationError("cross_division needs at least two divisions.")
        if cross_division.pairing not in PAIRINGS:
            raise ValidationError(f"cross_division.pairing must be one of {sorted(PAIRINGS)}.")
        if cross_division.pairing != "round_robin" and cross_division.games_per_team < 1:
            raise ValidationError("cross_division.games_per_team must be >= 1.")

    rosters = snake_pool_assignment(participants, divisions)
    home_counts: dict[Any, int] = {p.id: 0 for p in participants}
    division_schedules = [
        _division_schedule([p.id for p in roster], double, home_counts) for roster in rosters
    ]
    intra_total = max((len(s) for s in division_schedules), default=0)

    # Unified matchweeks: each entry is a list of (home_id, away_id, division | None-for-cross).
    week_fixtures: list[list[tuple[Any, Any, int | None]]] = []
    for week_index in range(intra_total):
        fixtures: list[tuple[Any, Any, int | None]] = []
        for div_index, sched in enumerate(division_schedules):
            if week_index < len(sched):
                fixtures.extend((home, away, div_index) for home, away in sched[week_index])
        week_fixtures.append(fixtures)

    if cross_division is not None:
        rng = random.Random(cross_division.seed)
        cross_pairs = _cross_pairings(
            [[p.id for p in roster] for roster in rosters], cross_division, rng
        )
        cross_fixtures: list[tuple[Any, Any]] = []
        for a, b in cross_pairs:
            home, away = _assign_home(a, b, home_counts)
            cross_fixtures.append((home, away))
            if cross_division.repeat_home_away:
                cross_fixtures.append((away, home))
        for cross_week in _schedule_into_weeks(cross_fixtures):
            week_fixtures.append([(home, away, None) for home, away in cross_week])

    total = len(week_fixtures)
    id_gen = IdGen()
    matches: list[Match] = []
    rounds: list[Round] = []
    for week_index, fixtures in enumerate(week_fixtures):
        week = week_index + 1
        match_ids: list[int] = []
        for home, away, division in fixtures:
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
    if cross_division is not None:
        config["cross_division"] = cross_division

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


def league_schedule(bracket: Bracket) -> list[Matchweek]:
    """A read-model of the season: matchweeks, each with its fixtures (home/away/division).

    Assembled from the rounds and per-match schedule metadata — convenient for UIs — without
    storing a second copy. The TO's edits to ``matchweek``/``home_id``/``away_id`` are reflected.
    """
    by_week: dict[int, list[Fixture]] = {}
    for m in bracket.matches:
        week = int(m.metadata.get("matchweek", m.round_number))
        by_week.setdefault(week, []).append(
            Fixture(
                match_id=m.id,
                home_id=m.metadata.get("home_id", m.participant1_id),
                away_id=m.metadata.get("away_id", m.participant2_id),
                division=m.metadata.get("division"),
            )
        )
    return [Matchweek(number=week, fixtures=by_week[week]) for week in sorted(by_week)]
