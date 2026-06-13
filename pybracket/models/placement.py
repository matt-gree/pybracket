from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Placement"]


@dataclass
class Placement:
    participant_id: Any
    position: int  # 1st, 2nd, 3rd, 4th, etc.
    position_label: str  # '1st', 'Top 4', 'Top 8', etc.
    eliminated_in: str  # Round name where participant was eliminated
