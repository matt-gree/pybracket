from __future__ import annotations

__all__ = [
    "PybracketError",
    "BracketStateError",
    "MatchNotFoundError",
    "ParticipantNotFoundError",
    "InvalidResultError",
    "ReseedError",
    "SwissRoundIncompleteError",
    "ValidationError",
]


class PybracketError(Exception):
    """Base class for all pybracket errors."""


class BracketStateError(PybracketError):
    """Operation not valid in the current bracket state."""


class MatchNotFoundError(PybracketError):
    """match_id not in bracket."""


class ParticipantNotFoundError(PybracketError):
    """participant_id not in match."""


class InvalidResultError(PybracketError):
    """winner_id not a participant in the match."""


class ReseedError(PybracketError):
    """Reseeding conflict with completed matches."""


class SwissRoundIncompleteError(PybracketError):
    """advance_swiss_round() called before current round done."""


class ValidationError(PybracketError):
    """Input validation failure (duplicate ids, bad seeds, empty field, etc.)."""
