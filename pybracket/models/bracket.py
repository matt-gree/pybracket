from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import BracketState
from .match import Match
from .participant import Participant
from .round import Round

__all__ = ["Bracket"]


@dataclass
class Bracket:
    format: str  # 'single_elim', 'double_elim', etc.
    state: BracketState
    participants: list[Participant]
    matches: list[Match]
    rounds: list[Round]
    config: dict[str, Any] = field(default_factory=dict)
    # config keys by format:
    #   single_elim:  third_place_match (bool)
    #   double_elim:  grand_final_reset (bool)
    #   swiss:        rounds (int), pairing_method (PairingMethod),
    #                 tiebreakers (list[str]), allow_bye (bool)
    #   pools:        num_pools (int), advancement_count (int),
    #                 bracket_format (str), snake_shuffle (bool)
    #   gauntlet:     style ('single' | 'dual'), opponent_choice (bool),
    #                 choice_scope ('round' | 'semifinals')
