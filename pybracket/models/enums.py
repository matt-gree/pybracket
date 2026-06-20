from __future__ import annotations

from enum import Enum

__all__ = [
    "MatchStatus",
    "BracketSide",
    "AdvancementType",
    "BracketState",
    "PairingMethod",
    "BracketFormat",
]


class MatchStatus(Enum):
    PENDING = "pending"  # Waiting on a prior match to resolve
    READY = "ready"  # Both participants known, match can be played
    BYE = "bye"  # Auto-advance, no game played
    COMPLETED = "completed"  # Result reported
    PENDING_CHOICE = "pending_choice"  # Gauntlet: higher seed must pick an opponent first
    NOT_NEEDED = "not_needed"  # Match existed in the structure but was never required to be played


class BracketSide(Enum):
    WINNERS = "winners"
    LOSERS = "losers"
    GRAND_FINAL = "grand_final"


class AdvancementType(Enum):
    RESULT = "result"  # Normal match result
    BYE = "bye"  # Planned bye (no opponent)
    FORFEIT = "forfeit"  # Opponent no-showed or withdrew mid-match
    WALKOVER = "walkover"  # Opponent disqualified


class BracketState(Enum):
    DRAFT = "draft"  # TO still editing seeds/config, not started
    PUBLISHED = "published"  # Bracket locked, matches being played
    COMPLETE = "complete"  # All matches resolved


class PairingMethod(Enum):
    MONRAD = "monrad"
    DUTCH = "dutch"


class BracketFormat(Enum):
    SINGLE_ELIM = "single_elim"
    DOUBLE_ELIM = "double_elim"
    ROUND_ROBIN = "round_robin"
    SWISS = "swiss"
    GAUNTLET = "gauntlet"
    # "pools" is not a bracket format: it is a phase of N parallel round-robin brackets
    # (Phase(format="round_robin", groups=N)). See pybracket/tournament.py.
