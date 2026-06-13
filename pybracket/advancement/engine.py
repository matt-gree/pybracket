from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..errors import (
    BracketStateError,
    InvalidResultError,
    MatchNotFoundError,
)
from ..models.bracket import Bracket
from ..models.enums import AdvancementType, BracketSide, BracketState, MatchStatus
from ..models.match import Match
from ..models.participant import Participant

__all__ = [
    "UnwindSignal",
    "report_result",
    "report_choice",
    "unwind_result",
    "get_ready_matches",
    "is_complete",
    "get_winner",
    "get_participant",
    "get_match",
    "compute_occupant_counts",
    "settle_initial",
    "REAL_RESULTS",
]

REAL_RESULTS = frozenset(
    {AdvancementType.RESULT, AdvancementType.FORFEIT, AdvancementType.WALKOVER}
)


@dataclass
class UnwindSignal:
    match_id: int
    metadata: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Indexing helpers
# --------------------------------------------------------------------------------------


def _index(bracket: Bracket) -> dict[int, Match]:
    return {m.id: m for m in bracket.matches}


def _incoming(bracket: Bracket) -> dict[int, list[tuple[int, str]]]:
    """For each match id, the (source_match_id, 'winner'|'loser') feeders pointing to it."""
    inc: dict[int, list[tuple[int, str]]] = {m.id: [] for m in bracket.matches}
    for m in bracket.matches:
        if m.next_winner_match_id is not None and m.next_winner_match_id in inc:
            inc[m.next_winner_match_id].append((m.id, "winner"))
        if m.next_loser_match_id is not None and m.next_loser_match_id in inc:
            inc[m.next_loser_match_id].append((m.id, "loser"))
    return inc


def _is_reset_match(m: Match) -> bool:
    return m.bracket_side is BracketSide.GRAND_FINAL and m.round_number == 2


def compute_occupant_counts(bracket: Bracket) -> dict[int, int]:
    """How many real participants will ever occupy each match (0, 1, or 2).

    A count of 1 means the match is a bye (its lone participant auto-advances); 0 means a
    phantom slot that exists only to keep the bracket a clean power of two.
    """
    matches = _index(bracket)
    incoming = _incoming(bracket)
    memo: dict[int, int] = {}

    def delivery(src: int, kind: str) -> int:
        c = count(src)
        if kind == "winner":
            return 1 if c >= 1 else 0
        return 1 if c >= 2 else 0  # only real matches (2 players) produce a loser

    def count(mid: int) -> int:
        if mid in memo:
            return memo[mid]
        memo[mid] = 0  # guard (DAG, but be safe)
        m = matches[mid]
        feeders = incoming[mid]
        if not feeders:
            c = (m.participant1_id is not None) + (m.participant2_id is not None)
        else:
            base_concrete = max(0, 2 - len(feeders))
            c = base_concrete + sum(delivery(src, kind) for src, kind in feeders)
        c = min(2, c)
        memo[mid] = c
        return c

    return {mid: count(mid) for mid in matches}


# --------------------------------------------------------------------------------------
# Slot delivery + bye resolution
# --------------------------------------------------------------------------------------


def _place(match: Match, participant_id: Any) -> None:
    """Place a participant into the lowest-index empty slot of a match."""
    if match.participant1_id is None:
        match.participant1_id = participant_id
    elif match.participant2_id is None:
        match.participant2_id = participant_id


def _present_id(match: Match) -> Any | None:
    return match.participant1_id if match.participant1_id is not None else match.participant2_id


def _filled_count(match: Match) -> int:
    return (match.participant1_id is not None) + (match.participant2_id is not None)


def _resolve_byes_forward(
    bracket: Bracket,
    counts: dict[int, int],
    matches: dict[int, Match],
    start: list[int],
) -> None:
    """Resolve any bye matches reachable from `start`, delivering their winners onward."""
    queue: deque[int] = deque(start)
    while queue:
        mid = queue.popleft()
        m = matches[mid]
        if m.status in (MatchStatus.COMPLETED, MatchStatus.BYE):
            continue
        if _is_reset_match(m):
            continue
        cnt = counts[mid]
        if cnt <= 1 and _filled_count(m) >= cnt and not (cnt == 1 and _filled_count(m) == 0):
            # Bye (cnt == 1, single participant present) or phantom (cnt == 0).
            winner = _present_id(m) if cnt == 1 else None
            m.winner_id = winner
            m.loser_id = None
            m.advancement_type = AdvancementType.BYE
            m.status = MatchStatus.BYE
            if winner is not None and m.next_winner_match_id is not None:
                target = matches[m.next_winner_match_id]
                _place(target, winner)
                queue.append(target.id)


def _recompute_statuses(bracket: Bracket, counts: dict[int, int]) -> None:
    for m in bracket.matches:
        if m.status in (MatchStatus.COMPLETED, MatchStatus.BYE, MatchStatus.NOT_NEEDED):
            continue
        if m.status is MatchStatus.PENDING_CHOICE:
            continue
        if _is_reset_match(m):
            continue
        cnt = counts[m.id]
        if cnt >= 2 and _filled_count(m) == 2:
            m.status = MatchStatus.READY
        else:
            m.status = MatchStatus.PENDING
    _refresh_state(bracket)


def _refresh_state(bracket: Bracket) -> None:
    if bracket.state is BracketState.DRAFT:
        return
    if is_complete(bracket):
        bracket.state = BracketState.COMPLETE
    else:
        bracket.state = BracketState.PUBLISHED


def settle_initial(bracket: Bracket) -> None:
    """Resolve construction-time byes and set initial statuses (in place)."""
    counts = compute_occupant_counts(bracket)
    matches = _index(bracket)
    _resolve_byes_forward(bracket, counts, matches, [m.id for m in bracket.matches])
    _recompute_statuses(bracket, counts)


def _apply_format_hooks(bracket: Bracket) -> None:
    """Run format-specific post-processing (e.g. gauntlet opponent-choice frontiers)."""
    if bracket.format == "gauntlet" and bracket.config.get("opponent_choice"):
        if bracket.config.get("style") == "dual" and bracket.config.get("choice_scope") == "round":
            from ..formats.gauntlet import refresh_gauntlet_round_choices

            refresh_gauntlet_round_choices(bracket)
        else:
            from ..formats.gauntlet import refresh_gauntlet_choices

            refresh_gauntlet_choices(bracket)


# --------------------------------------------------------------------------------------
# Public: report / unwind
# --------------------------------------------------------------------------------------


def get_match(bracket: Bracket, match_id: int) -> Match | None:
    for m in bracket.matches:
        if m.id == match_id:
            return m
    return None


def get_participant(bracket: Bracket, participant_id: Any) -> Participant | None:
    if participant_id is None:
        return None
    for p in bracket.participants:
        if p.id == participant_id:
            return p
    return None


def _require_match(bracket: Bracket, match_id: int) -> Match:
    m = get_match(bracket, match_id)
    if m is None:
        raise MatchNotFoundError(f"No match with id {match_id}.")
    return m


def _grand_final_matches(bracket: Bracket) -> tuple[Match | None, Match | None]:
    gf = reset = None
    for m in bracket.matches:
        if m.bracket_side is BracketSide.GRAND_FINAL:
            if m.round_number == 1:
                gf = m
            elif m.round_number == 2:
                reset = m
    return gf, reset


def _loser_bracket_final(bracket: Bracket) -> Match | None:
    for m in bracket.matches:
        if (
            m.bracket_side is BracketSide.LOSERS
            and m.next_winner_match_id is not None
        ):
            target = get_match(bracket, m.next_winner_match_id)
            if target is not None and target.bracket_side is BracketSide.GRAND_FINAL:
                return m
    return None


def report_result(
    bracket: Bracket,
    match_id: int,
    winner_id: Any,
    advancement_type: AdvancementType = AdvancementType.RESULT,
    metadata: dict[str, Any] | None = None,
) -> Bracket:
    """Report a match result, returning a new bracket with the result advanced."""
    if advancement_type not in REAL_RESULTS:
        raise InvalidResultError(
            "advancement_type must be RESULT, FORFEIT, or WALKOVER for report_result()."
        )

    b = copy.deepcopy(bracket)
    matches = _index(b)
    m = _require_match(b, match_id)

    if m.status is MatchStatus.COMPLETED:
        raise BracketStateError(
            f"Match {match_id} is already completed; unwind_result() it first."
        )
    if m.status is MatchStatus.PENDING_CHOICE:
        raise BracketStateError(
            f"Match {match_id} is awaiting an opponent choice; call report_choice() first."
        )
    if winner_id not in (m.participant1_id, m.participant2_id) or winner_id is None:
        raise InvalidResultError(
            f"winner_id {winner_id!r} is not a participant in match {match_id}."
        )

    loser_id = (
        m.participant2_id if winner_id == m.participant1_id else m.participant1_id
    )
    m.winner_id = winner_id
    m.loser_id = loser_id
    m.advancement_type = advancement_type
    m.status = MatchStatus.COMPLETED
    if metadata is not None:
        m.metadata = {**m.metadata, **metadata}

    touched: list[int] = []
    if m.next_winner_match_id is not None:
        target = matches[m.next_winner_match_id]
        _place(target, winner_id)
        touched.append(target.id)
    if m.next_loser_match_id is not None and loser_id is not None:
        ltarget = matches[m.next_loser_match_id]
        _place(ltarget, loser_id)
        touched.append(ltarget.id)

    # Grand final -> reset activation / settlement.
    gf, reset = _grand_final_matches(b)
    if gf is not None and m.id == gf.id and reset is not None:
        lb_final = _loser_bracket_final(b)
        lb_winner = lb_final.winner_id if lb_final is not None else None
        reset_enabled = bool(b.config.get("grand_final_reset", True))
        if reset_enabled and lb_winner is not None and winner_id == lb_winner:
            # The loser-bracket finalist took the first set: play the reset.
            reset.participant1_id = m.participant1_id
            reset.participant2_id = m.participant2_id
            reset.status = MatchStatus.READY
        elif reset.status is MatchStatus.PENDING:
            # The winners-bracket finalist won outright (or the reset is disabled): the
            # reset match exists in the structure but is never required. It is not a bye —
            # no participant advances through it; it simply closes.
            reset.status = MatchStatus.NOT_NEEDED

    counts = compute_occupant_counts(b)
    _resolve_byes_forward(b, counts, matches, touched)
    _recompute_statuses(b, counts)
    _apply_format_hooks(b)
    return b


def report_choice(
    bracket: Bracket,
    match_id: int,
    chosen_opponent_id: Any,
) -> Bracket:
    """Resolve a gauntlet opponent choice, making the match READY."""
    b = copy.deepcopy(bracket)
    m = _require_match(b, match_id)
    if m.status is not MatchStatus.PENDING_CHOICE:
        raise BracketStateError(f"Match {match_id} is not awaiting an opponent choice.")

    pool = m.metadata.get("choice_pool", [])
    if chosen_opponent_id not in pool:
        raise InvalidResultError(
            f"{chosen_opponent_id!r} is not an available opponent for match {match_id}."
        )

    if m.metadata.get("gauntlet_role") == "chooser":
        _resolve_dual_gauntlet_choice(b, m, chosen_opponent_id)
        return b

    # Generic case: the chooser occupies one slot; fill the other with the chosen opponent.
    _place(m, chosen_opponent_id)
    m.status = MatchStatus.READY
    for other in b.matches:
        if other.id != m.id and other.status is MatchStatus.PENDING_CHOICE:
            remaining = [
                pid for pid in other.metadata.get("choice_pool", []) if pid != chosen_opponent_id
            ]
            other.metadata = {**other.metadata, "choice_pool": remaining}
    return b


def _resolve_dual_gauntlet_choice(b: Bracket, chooser: Match, chosen: Any) -> None:
    """Seed 1 picks a survivor; if it is not the default, swap the two semifinals' survivors."""
    matches = _index(b)
    other = matches[chooser.metadata["choice_other_match"]]
    default_survivor = chooser.participant2_id
    other_survivor = other.participant2_id

    if chosen != default_survivor:
        chooser.participant2_id = other_survivor
        other.participant2_id = default_survivor
        # Keep sub-bracket feeder pointers consistent so a later unwind clears the right slot.
        for src in b.matches:
            if src.next_winner_match_id == chooser.id and src.winner_id == default_survivor:
                src.next_winner_match_id = other.id
            elif src.next_winner_match_id == other.id and src.winner_id == other_survivor:
                src.next_winner_match_id = chooser.id

    chooser.metadata = {
        k: v for k, v in chooser.metadata.items() if k != "choice_pool"
    }
    chooser.metadata["choice_made"] = True
    other.metadata = {**other.metadata, "choice_made": True}
    chooser.status = MatchStatus.READY
    other.status = MatchStatus.READY


def unwind_result(
    bracket: Bracket,
    match_id: int,
) -> tuple[Bracket, list[UnwindSignal]]:
    """Clear a result and cascade downstream, returning the new bracket and unwind signals."""
    b = copy.deepcopy(bracket)
    matches = _index(b)
    m = _require_match(b, match_id)
    if m.advancement_type not in REAL_RESULTS:
        raise BracketStateError(
            f"Match {match_id} has no reported result to unwind."
        )

    signals: list[UnwindSignal] = []
    gf, reset = _grand_final_matches(b)
    queue: deque[int] = deque([match_id])
    visited: set[int] = set()

    while queue:
        mid = queue.popleft()
        if mid in visited:
            continue
        visited.add(mid)
        cur = matches[mid]

        # Clear placed participants downstream and cascade into completed matches.
        downstream: list[tuple[int | None, Any]] = [
            (cur.next_winner_match_id, cur.winner_id),
            (cur.next_loser_match_id, cur.loser_id),
        ]
        # Grand final first set feeds the reset match specially.
        if cur.bracket_side is BracketSide.GRAND_FINAL and cur.round_number == 1 and reset is not None:
            downstream.append((reset.id, cur.participant1_id))
            downstream.append((reset.id, cur.participant2_id))

        for target_id, value in downstream:
            if target_id is None or value is None:
                continue
            target = matches[target_id]
            cleared = False
            if target.participant1_id == value:
                target.participant1_id = None
                cleared = True
            elif target.participant2_id == value:
                target.participant2_id = None
                cleared = True
            if cleared and target.status in (MatchStatus.COMPLETED, MatchStatus.BYE):
                queue.append(target_id)
            elif cleared and _is_reset_match(target):
                target.status = MatchStatus.PENDING
                target.winner_id = None
                target.loser_id = None
                target.advancement_type = None

        # Unwinding the grand final's first set re-opens a reset that had settled to
        # NOT_NEEDED (no participants were ever placed there, so nothing was "cleared").
        if (
            cur.bracket_side is BracketSide.GRAND_FINAL
            and cur.round_number == 1
            and reset is not None
            and reset.status is MatchStatus.NOT_NEEDED
        ):
            reset.status = MatchStatus.PENDING

        if cur.advancement_type in REAL_RESULTS:
            signals.append(UnwindSignal(match_id=cur.id, metadata=dict(cur.metadata)))

        # Clear this match's own result.
        cur.winner_id = None
        cur.loser_id = None
        cur.advancement_type = None
        if cur.status in (MatchStatus.COMPLETED, MatchStatus.BYE):
            cur.status = MatchStatus.READY

    counts = compute_occupant_counts(b)
    # Re-resolve byes that may have been cleared, then recompute statuses.
    _resolve_byes_forward(b, counts, matches, list(visited))
    _recompute_statuses(b, counts)
    # Re-open or re-close format-specific frontiers (e.g. gauntlet opponent choices) whose
    # inputs changed as a result of the unwind.
    _apply_format_hooks(b)
    return b, signals


# --------------------------------------------------------------------------------------
# Public: queries
# --------------------------------------------------------------------------------------


def get_ready_matches(bracket: Bracket) -> list[Match]:
    """Matches that can be played right now: both participants known and status READY."""
    ready: list[Match] = []
    for m in bracket.matches:
        if (
            m.status is MatchStatus.READY
            and m.participant1_id is not None
            and m.participant2_id is not None
        ):
            ready.append(m)
    return ready


def is_complete(bracket: Bracket) -> bool:
    """True when no match remains to be played."""
    if bracket.format == "swiss":
        target = int(bracket.config.get("rounds", 0))
        generated = max((m.round_number for m in bracket.matches), default=0)
        if generated < target:
            return False
    for m in bracket.matches:
        if _is_reset_match(m):
            # The reset only counts if it was activated (READY) and not yet completed.
            if m.status is MatchStatus.READY:
                return False
            continue
        if m.status in (MatchStatus.READY, MatchStatus.PENDING, MatchStatus.PENDING_CHOICE):
            return False
    return True


def get_winner(bracket: Bracket) -> Participant | None:
    """The overall tournament winner, or None if not yet decided."""
    if not is_complete(bracket):
        return None
    if bracket.format in ("round_robin", "swiss"):
        from ..tiebreakers.standings import get_standings

        standings = get_standings(bracket)
        if standings:
            return get_participant(bracket, standings[0].participant_id)
        return None
    gf, reset = _grand_final_matches(bracket)
    if gf is not None:
        decider = reset if (reset is not None and reset.status is MatchStatus.COMPLETED) else gf
        if decider.winner_id is not None:
            return get_participant(bracket, decider.winner_id)
    # Single elimination / gauntlet: winner of the last winners-side match.
    final = _overall_final(bracket)
    if final is not None and final.winner_id is not None:
        return get_participant(bracket, final.winner_id)
    return None


def _overall_final(bracket: Bracket) -> Match | None:
    """The match whose winner is the champion (excludes consolation/third-place matches)."""
    candidates = [
        m
        for m in bracket.matches
        if m.next_winner_match_id is None
        and m.bracket_side in (BracketSide.WINNERS, BracketSide.GRAND_FINAL)
        and not m.metadata.get("consolation")
    ]
    if not candidates:
        return None
    # The true final is the highest-round winners/grand-final match.
    return max(candidates, key=lambda m: (m.bracket_side is BracketSide.GRAND_FINAL, m.round_number))
