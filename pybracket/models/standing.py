from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import AdvancementType

__all__ = ["Standing"]


@dataclass
class Standing:
    participant_id: Any
    rank: int
    wins: int
    losses: int
    advancement_type_counts: dict[AdvancementType, int] = field(default_factory=dict)
    # Tracks how many results were by forfeit, walkover, bye, or normal result.
    # Callers can decide whether to include forfeits in win/loss display.
    tiebreaker_scores: dict[str, float] = field(default_factory=dict)
    # Keyed by tiebreaker class name.
