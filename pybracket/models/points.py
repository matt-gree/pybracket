from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["PointsSystem"]


@dataclass(frozen=True)
class PointsSystem:
    """Points awarded per result for standings-based formats.

    Stored in the bracket/phase config (``config["points_system"]``). With one set, standings
    rank by points first, then the tiebreaker chain; without one, ranking is by record as before.
    ``draws_allowed`` gates whether ``report_draw`` (and even-best-of level series) are permitted.
    """

    win: int = 3
    draw: int = 1
    loss: int = 0
    draws_allowed: bool = True

    def points_for(self, wins: int, draws: int, losses: int) -> float:
        return float(self.win * wins + self.draw * draws + self.loss * losses)

    def to_spec(self) -> dict[str, Any]:
        return {
            "win": self.win,
            "draw": self.draw,
            "loss": self.loss,
            "draws_allowed": self.draws_allowed,
        }

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> PointsSystem:
        return cls(
            win=int(spec.get("win", 3)),
            draw=int(spec.get("draw", 1)),
            loss=int(spec.get("loss", 0)),
            draws_allowed=bool(spec.get("draws_allowed", True)),
        )
