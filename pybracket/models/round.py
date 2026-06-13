from __future__ import annotations

from dataclasses import dataclass

from .enums import BracketSide

__all__ = ["Round"]


@dataclass
class Round:
    number: int
    bracket_side: BracketSide
    match_ids: list[int]
    name: str  # Human-readable. See naming/round_names.py
    best_of: int | None = None  # If set at round level, overrides match defaults
