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
    draws: int = 0
    points: float = 0.0
    # draws/points populated for standings formats; points is 0 unless a PointsSystem is set.
    advancement_type_counts: dict[AdvancementType, int] = field(default_factory=dict)
    # Tracks how many results were by forfeit, walkover, bye, draw, or normal result.
    # Callers can decide whether to include forfeits in win/loss display.
    tiebreaker_scores: dict[str, float] = field(default_factory=dict)
    # Keyed by tiebreaker class name.
