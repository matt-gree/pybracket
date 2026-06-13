"""pybracket — a storage-agnostic, game-agnostic tournament bracket library."""

from __future__ import annotations

from .advancement import (
    UnwindSignal,
    get_match,
    get_participant,
    get_placements,
    get_ready_matches,
    get_winner,
    is_complete,
    report_choice,
    report_result,
    unwind_result,
)
from .errors import (
    BracketStateError,
    InvalidResultError,
    MatchNotFoundError,
    ParticipantNotFoundError,
    PybracketError,
    ReseedError,
    SwissRoundIncompleteError,
    ValidationError,
)
from .formats import (
    PoolsBracket,
    advance_swiss_round,
    draft_pools_to_bracket,
    generate_double_elim,
    generate_gauntlet,
    generate_pools,
    generate_round_robin,
    generate_single_elim,
    generate_swiss,
    publish_bracket,
    reseed_pools_to_bracket,
)
from .models import (
    AdvancementType,
    Bracket,
    BracketFormat,
    BracketSide,
    BracketState,
    Match,
    MatchStatus,
    PairingMethod,
    Participant,
    Placement,
    Round,
    Standing,
)
from .operations import reseed, set_best_of
from .tiebreakers import (
    BuchholzTiebreaker,
    HeadToHeadTiebreaker,
    StatTiebreaker,
    Tiebreaker,
    WinCountTiebreaker,
    get_standings,
)
from .utils import (
    bracket_from_dict,
    bracket_from_json,
    bracket_to_dict,
    bracket_to_json,
    next_power_of_2,
    recommend_pool_count,
    recommend_swiss_rounds,
)

__version__ = "0.1.0"

__all__ = [
    # Models
    "AdvancementType",
    "Bracket",
    "BracketFormat",
    "BracketSide",
    "BracketState",
    "Match",
    "MatchStatus",
    "PairingMethod",
    "Participant",
    "Placement",
    "Round",
    "Standing",
    # Generation
    "generate_single_elim",
    "generate_double_elim",
    "generate_round_robin",
    "generate_swiss",
    "generate_pools",
    "generate_gauntlet",
    "PoolsBracket",
    # Result reporting
    "report_result",
    "report_choice",
    "unwind_result",
    "UnwindSignal",
    # Querying
    "get_ready_matches",
    "get_standings",
    "get_placements",
    "is_complete",
    "get_winner",
    "get_participant",
    "get_match",
    # Swiss
    "recommend_swiss_rounds",
    "advance_swiss_round",
    # Reseeding / config
    "reseed",
    "draft_pools_to_bracket",
    "publish_bracket",
    "reseed_pools_to_bracket",
    "set_best_of",
    # Tiebreakers
    "Tiebreaker",
    "WinCountTiebreaker",
    "HeadToHeadTiebreaker",
    "BuchholzTiebreaker",
    "StatTiebreaker",
    # Utilities
    "next_power_of_2",
    "recommend_pool_count",
    "bracket_to_dict",
    "bracket_from_dict",
    "bracket_to_json",
    "bracket_from_json",
    # Errors
    "PybracketError",
    "BracketStateError",
    "MatchNotFoundError",
    "ParticipantNotFoundError",
    "InvalidResultError",
    "ReseedError",
    "SwissRoundIncompleteError",
    "ValidationError",
]
