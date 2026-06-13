from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from ..models.participant import Participant

__all__ = [
    "validate_participants",
    "ensure_no_duplicate_ids",
    "ensure_unique_seeds",
]


def ensure_no_duplicate_ids(participants: list[Participant]) -> None:
    seen: set[Any] = set()
    for p in participants:
        if p.id in seen:
            raise ValidationError(f"Duplicate participant id: {p.id!r}")
        seen.add(p.id)


def ensure_unique_seeds(participants: list[Participant]) -> None:
    seeds = [p.seed for p in participants]
    if len(set(seeds)) != len(seeds):
        raise ValidationError("Participants have duplicate seeds.")
    if any(s < 1 for s in seeds):
        raise ValidationError("Seeds must be 1-indexed (>= 1).")


def validate_participants(participants: list[Participant], minimum: int = 2) -> None:
    """Validate a participant list: non-empty, no duplicate ids, unique positive seeds."""
    if len(participants) < minimum:
        raise ValidationError(
            f"Need at least {minimum} participants, got {len(participants)}."
        )
    for p in participants:
        if not p.name:
            raise ValidationError(f"Participant {p.id!r} has an empty name.")
    ensure_no_duplicate_ids(participants)
    ensure_unique_seeds(participants)
