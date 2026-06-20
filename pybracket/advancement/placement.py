from __future__ import annotations

from typing import Any

from ..models.bracket import Bracket
from ..models.enums import BracketSide, MatchStatus
from ..models.match import Match
from ..models.placement import Placement
from ..naming.round_names import ordinal
from .engine import get_winner, is_complete

__all__ = ["get_placements"]

_STAGE_OFFSET = {
    BracketSide.WINNERS: 0,
    BracketSide.LOSERS: 1000,
    BracketSide.GRAND_FINAL: 2000,
}


def _stage_value(m: Match) -> int:
    return _STAGE_OFFSET[m.bracket_side] + m.round_number


def _round_name_of(bracket: Bracket, match_id: int) -> str:
    for r in bracket.rounds:
        if match_id in r.match_ids:
            return r.name
    return ""


def get_placements(bracket: Bracket) -> list[Placement]:
    """Final placements computed from bracket structure (only meaningful once complete)."""
    if bracket.format in ("round_robin", "swiss", "league"):
        return _standings_placements(bracket)
    if bracket.config.get("truncated_to"):
        return _truncated_placements(bracket)
    return _elimination_placements(bracket)


def _truncated_placements(bracket: Bracket) -> list[Placement]:
    """Placements for a truncated single-elim qualifier bracket: the winners of the last played
    round are co-survivors at the top (ranked among themselves by seed), and everyone else is
    placed by the round in which they lost."""
    survivors_n = int(bracket.config["truncated_to"])
    seed_of = {p.id: p.seed for p in bracket.participants}
    played = [
        m
        for m in bracket.matches
        if m.status is MatchStatus.COMPLETED and not m.metadata.get("consolation")
    ]
    last_round = max((m.round_number for m in played), default=0)

    survivors = [
        m.winner_id
        for m in played
        if m.round_number == last_round and m.winner_id is not None
    ]
    survivors.sort(key=lambda pid: seed_of.get(pid, 0))
    placements: list[Placement] = [
        Placement(
            participant_id=pid,
            position=pos,
            position_label=f"Top {survivors_n}",
            eliminated_in="",
        )
        for pos, pid in enumerate(survivors, start=1)
    ]

    # Losers ranked by the round they exited in (later round = better placement).
    losers = [(m.round_number, m.loser_id, m.id) for m in played if m.loser_id is not None]
    losers.sort(key=lambda t: (-t[0], seed_of.get(t[1], 0)))
    position = survivors_n + 1
    i = 0
    while i < len(losers):
        rnd = losers[i][0]
        group = [t for t in losers[i:] if t[0] == rnd]
        upper = position + len(group) - 1
        label = ordinal(position) if len(group) == 1 else f"Top {upper}"
        for _, pid, match_id in group:
            placements.append(
                Placement(
                    participant_id=pid,
                    position=position,
                    position_label=label,
                    eliminated_in=_round_name_of(bracket, match_id),
                )
            )
            position += 1
        i += len(group)
    return placements


def _standings_placements(bracket: Bracket) -> list[Placement]:
    from ..tiebreakers.standings import get_standings

    standings = get_standings(bracket)
    final_round = bracket.rounds[-1].name if bracket.rounds else ""
    placements: list[Placement] = []
    for s in standings:
        placements.append(
            Placement(
                participant_id=s.participant_id,
                position=s.rank,
                position_label=ordinal(s.rank),
                eliminated_in="" if s.rank == 1 else final_round,
            )
        )
    return placements


def _elimination_placements(bracket: Bracket) -> list[Placement]:
    champion = get_winner(bracket)
    champion_id = champion.id if champion is not None else None

    # Each participant's last contested (non-consolation) completed match.
    last_match: dict[Any, Match] = {}
    consolation: Match | None = None
    for m in bracket.matches:
        if m.metadata.get("consolation"):
            if m.status is MatchStatus.COMPLETED:
                consolation = m
            continue
        if m.status is not MatchStatus.COMPLETED:
            continue
        for pid in (m.participant1_id, m.participant2_id):
            if pid is None:
                continue
            prev = last_match.get(pid)
            if prev is None or _stage_value(m) > _stage_value(prev):
                last_match[pid] = m

    placements: list[Placement] = []
    if champion_id is not None:
        placements.append(
            Placement(
                participant_id=champion_id,
                position=1,
                position_label="1st",
                eliminated_in="",
            )
        )

    eliminated = [pid for pid in last_match if pid != champion_id]
    seed_of = {p.id: p.seed for p in bracket.participants}
    eliminated.sort(key=lambda pid: (-_stage_value(last_match[pid]), seed_of.get(pid, 0)))

    position = 2
    i = 0
    while i < len(eliminated):
        value = _stage_value(last_match[eliminated[i]])
        group = [pid for pid in eliminated[i:] if _stage_value(last_match[pid]) == value]
        size = len(group)
        upper = position + size - 1
        label = ordinal(position) if size == 1 else f"Top {upper}"
        for pid in group:
            placements.append(
                Placement(
                    participant_id=pid,
                    position=position,
                    position_label=label,
                    eliminated_in=_round_name_of(bracket, last_match[pid].id),
                )
            )
            position += 1
        i += size

    if consolation is not None and consolation.winner_id is not None:
        _apply_consolation(placements, consolation)

    return placements


def _apply_consolation(placements: list[Placement], consolation: Match) -> None:
    winner = consolation.winner_id
    loser = consolation.loser_id
    for p in placements:
        if p.participant_id == winner:
            p.position = 3
            p.position_label = "3rd"
            p.eliminated_in = "Third Place Match"
        elif p.participant_id == loser:
            p.position = 4
            p.position_label = "4th"
            p.eliminated_in = "Third Place Match"


# Re-exported for convenience; placement only matters once the bracket is complete.
def _placements_ready(bracket: Bracket) -> bool:
    return is_complete(bracket)
