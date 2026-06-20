from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bracket import Bracket
from .enums import BracketState
from .participant import Participant

__all__ = [
    "ALL_PLACES",
    "EACH_GROUP",
    "SlotRef",
    "Qualification",
    "Phase",
    "Tournament",
    "PhaseSpec",
    "Ranked",
]

# Sentinels used inside a SlotRef so the boundary wiring can be written before the upstream
# phase's exact size / group count is known. Both expand at resolution time (see tournament.py).
ALL_PLACES = 0  # place == 0  -> every finisher of the referenced group, in rank order
EACH_GROUP = -1  # group == -1 -> replicate this ref once per group of the source phase


@dataclass(frozen=True)
class SlotRef:
    """A reference to a ranked finishing position of an upstream phase.

    ``place`` is 1-based, or :data:`ALL_PLACES` to mean "every finisher". ``group`` is the
    0-based group index within the source phase, ``None`` for the phase's overall ranking, or
    :data:`EACH_GROUP` to mean "one ref per group". Resolves to a concrete participant only once
    the source phase is complete; before that it renders as a named placeholder for previews.
    """

    phase: str
    place: int = ALL_PLACES
    group: int | None = None


@dataclass
class Qualification:
    """How a phase's entrants are drawn from, and seeded out of, upstream phases."""

    sources: list[SlotRef]
    seeding: str = "snake"  # 'snake' | 'rank' | 'manual' (library recommends; TO overrides)


@dataclass
class Phase:
    id: str
    format: str
    config: dict[str, Any] = field(default_factory=dict)
    entrants: Qualification | None = None  # None = phase 0, seeded from the tournament field
    groups: int = 1
    group_assignment: str = "snake"  # how entrants split across groups (pools)
    brackets: list[Bracket] = field(default_factory=list)
    state: BracketState = BracketState.DRAFT


@dataclass
class Tournament:
    phases: list[Phase]
    participants: list[Participant]
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ranked:
    """A unified ranked finisher, the output of ``phase_results`` and what a ``SlotRef``
    resolves against. ``group`` records which sub-bracket the finisher came from."""

    participant_id: Any
    rank: int
    group: int = 0


@dataclass
class PhaseSpec:
    """Lightweight authoring form for a phase, passed to ``generate_tournament``."""

    id: str
    format: str
    groups: int = 1
    entrants: Qualification | None = None  # None for the first phase only
    group_assignment: str = "snake"
    config: dict[str, Any] = field(default_factory=dict)
