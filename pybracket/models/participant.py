from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Participant"]


@dataclass
class Participant:
    id: Any  # Caller-defined. int, UUID, str — library is agnostic.
    seed: int  # 1-indexed. Seed 1 = best.
    name: str
    stats: dict[str, Any] = field(default_factory=dict)
    # stats holds caller-defined values for tiebreakers, e.g.:
    # {'run_differential': 12, 'runs_scored': 45, 'glicko_rating': 1823}
