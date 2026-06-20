from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Game"]


@dataclass
class Game:
    """One game of a best-of-N series within a :class:`Match`.

    A match reported game-by-game (via ``report_game``) accumulates a ``Game`` per game; a
    match reported with the ``report_result`` shortcut keeps no game log. ``winner_id`` is
    ``None`` only for a drawn game (allowed where draws are enabled).
    """

    number: int  # 1-based position within the match's series
    winner_id: Any | None
    loser_id: Any | None
    stats: dict[str, dict[Any, float]] = field(default_factory=dict)
    # Blessed channel the ranking engine reads: {stat_name: {participant_id: value}}.
    metadata: dict[str, Any] = field(default_factory=dict)
    # Caller's per-game scratch (timestamps, raw scores, …). The engine never reads it.
