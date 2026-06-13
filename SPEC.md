# pybracket — Implementation Specification

A storage-agnostic, game-agnostic Python library for tournament bracket management.
Supports single elimination, double elimination, round robin, Swiss, pools, and gauntlet formats.

---

## Agent Instructions — Read Before Writing Any Code

Before writing a single line of implementation, the implementing agent must:

1. **Read all open issues and open PRs** on the reference repository:
   [https://github.com/Drarig29/brackets-manager.js](https://github.com/Drarig29/brackets-manager.js)
   Use these to understand known edge cases, unimplemented features, known bugs, and design
   decisions that were deliberately deferred. The goal is to not repeat their mistakes and to
   understand where their implementation falls short so pybracket improves on it.

2. **Read the following reference materials** before implementing each subsystem:

   **Swiss / Dutch Pairing (required before implementing `pairing/`):**
   - [FIDE Handbook C.04.3 — FIDE (Dutch) System](https://handbook.fide.com/chapter/C0403202602)
   - [FIDE General Handling Rules for Swiss Tournaments](https://handbook.fide.com/chapter/GeneralHandlingRulesForSwissTournaments202507)
   - [FIDE C.04 Swiss Rules — Full PDF](https://www.rrweb.org/javafo/C04.pdf)
   - [Wikipedia: Swiss-system tournament](https://en.wikipedia.org/wiki/Swiss-system_tournament)

   **Seeding Theory (required before implementing `seeding/`):**
   - [Optimal Seedings in Elimination Tournaments — Moldovanu et al.](https://www.econ.uni-bonn.de/micro/en/moldovanu/publications-1/seed-final.pdf/@@download/file/seed-final.pdf)
   - [Optimal Seedings Revisited — Springer](https://link.springer.com/article/10.1007/s40505-014-0030-z)
   - [A Theory of Knockout Tournament Seedings — Heidelberg](https://www.uni-heidelberg.de/md/awi/forschung/dp600.pdf)
   - [Who Can Win a Single-Elimination Tournament? — arXiv](https://arxiv.org/abs/1511.08416)
   - [Competitive Intensity and Quality Maximizing Seedings — Springer](https://link.springer.com/article/10.1007/s10878-017-0164-7)

   **Tournament Design Broadly (read for overall architecture):**
   - [Tournament Design: A Review from an OR Perspective — arXiv 2024](https://arxiv.org/pdf/2404.05034)
   - [The Efficacy of Tournament Designs — arXiv](https://arxiv.org/pdf/2103.06023)

   **Double Elimination Structure (required before implementing `formats/double_elim.py`):**
   - [Wikipedia: Double-elimination tournament](https://en.wikipedia.org/wiki/Double-elimination_tournament)
   - [Tournament Mechanics: A Primer — Smashboards](https://smashboards.com/threads/tournament-mechanics-a-primer.124132/)

3. **Read the brackets-manager.js source** as a reference implementation. Pay particular attention to:
   - `src/helpers.ts` — core bracket generation and placement algorithms
   - `src/base/stage/creator.ts` — stage creation and bye handling
   - `src/base/updater.ts` — match advancement logic
   - `test/double-elimination.spec.js` — double elimination edge cases
   - `test/update.spec.js` — result reporting and advancement
   - `test/single-elimination.spec.js` — single elimination edge cases

   Do **not** copy TypeScript verbatim. Port logic and translate tests to pytest.

---

## Attribution

pybracket is informed by and partially derived from
[brackets-manager.js](https://github.com/Drarig29/brackets-manager.js) by
[Drarig29](https://github.com/Drarig29), released under the MIT License.

The implementing agent must:
- Include the original MIT copyright notice from brackets-manager.js in `LICENSE` alongside
  the pybracket copyright notice.
- Include an "Acknowledgements" section in `README.md` crediting brackets-manager.js,
  its author, the FIDE Dutch pairing specification, and the academic seeding papers listed above.

---

## Design Principles

1. **Storage-agnostic.** The library never reads from or writes to a database. All operations
   accept Python dataclasses and return Python dataclasses. The caller handles persistence.

2. **Game-agnostic.** No game-specific logic. Rio-specific stats (run differential, etc.) are
   supported via the extensible `Participant.stats: dict` and `StatTiebreaker` — the library
   never references game-specific field names by name.

3. **Immutable-ish operations.** `report_result()`, `unwind_result()`, and round-advancing
   functions return a new `Bracket` instance rather than mutating in place. This makes the
   library easier to test, easier to reason about, and allows the caller to diff before/after
   to determine what changed.

4. **Library recommends, TO overrides.** Anywhere there are multiple valid interpretations
   (pool sizes, Swiss round count, bye assignment, pool snake shuffle), the library provides
   a sensible default with a clear override mechanism. No silent magic.

5. **Pytest throughout.** Tests are written alongside implementation — not after. Every format,
   every edge case, every pairing rule has a corresponding test. Tests derived from the FIDE
   handbook, the academic papers, and the brackets-manager.js test suite are clearly commented
   with their source.

6. **Type hints everywhere.** Python 3.10+. Full annotations on all public and private
   functions. Use `from __future__ import annotations` in all files. Run `mypy` in strict mode.

7. **No external runtime dependencies.** The core library (`pybracket/`) must have zero
   third-party runtime dependencies. `pytest`, `hypothesis`, `mypy`, and `ruff` are dev
   dependencies only.

---

## Repository Structure

```
pybracket/
├── LICENSE                        # MIT dual-attribution (see Attribution section)
├── README.md                      # Overview, quickstart, acknowledgements
├── SPEC.md                        # This file
├── CONTRIBUTING.md
├── pyproject.toml                 # Build config, dev deps, mypy/ruff settings
├── pybracket/
│   ├── __init__.py                # Public API surface — re-exports only
│   ├── models/
│   │   ├── __init__.py
│   │   ├── enums.py               # MatchStatus, BracketFormat, PairingMethod,
│   │   │                          # BracketSide, AdvancementType, BracketState
│   │   ├── participant.py         # Participant dataclass
│   │   ├── match.py               # Match dataclass
│   │   ├── round.py               # Round dataclass
│   │   ├── bracket.py             # Bracket dataclass (top-level container)
│   │   ├── standing.py            # Standing dataclass
│   │   └── placement.py          # Placement dataclass (final results)
│   ├── formats/
│   │   ├── __init__.py
│   │   ├── base.py                # BracketFormat abstract base class
│   │   ├── single_elim.py
│   │   ├── double_elim.py
│   │   ├── round_robin.py
│   │   ├── swiss.py
│   │   ├── pools.py               # Composition: round robin pools → bracket
│   │   └── gauntlet.py            # Single-sided and dual-sided gauntlet
│   ├── seeding/
│   │   ├── __init__.py
│   │   ├── algorithms.py          # standard, bracket-optimized, protected-seed ordering
│   │   └── pool_seeding.py        # Snake seeding + rematch-avoidance shuffle
│   ├── pairing/
│   │   ├── __init__.py
│   │   ├── monrad.py              # Monrad Swiss pairing
│   │   └── dutch.py               # FIDE Dutch Swiss pairing
│   ├── tiebreakers/
│   │   ├── __init__.py
│   │   ├── base.py                # Tiebreaker Protocol definition
│   │   ├── win_count.py
│   │   ├── head_to_head.py
│   │   ├── buchholz.py            # Standard and truncated Buchholz
│   │   └── stat_tiebreaker.py     # Generic stat key tiebreaker
│   ├── advancement/
│   │   ├── __init__.py
│   │   ├── engine.py              # report_result, unwind_result, bye resolution
│   │   └── placement.py           # Final placement calculation per format
│   ├── naming/
│   │   ├── __init__.py
│   │   └── round_names.py         # Human-readable round name generation
│   └── utils/
│       ├── __init__.py
│       ├── serialization.py       # Bracket ↔ JSON round-trip
│       ├── validation.py          # Input validation, participant dedup, seed checks
│       └── math.py                # next_power_of_2, recommend_swiss_rounds, etc.
└── tests/
    ├── conftest.py                # Shared fixtures: participants, small brackets
    ├── formats/
    │   ├── test_single_elim.py
    │   ├── test_double_elim.py
    │   ├── test_round_robin.py
    │   ├── test_swiss.py
    │   ├── test_pools.py
    │   └── test_gauntlet.py
    ├── seeding/
    │   ├── test_algorithms.py
    │   └── test_pool_seeding.py
    ├── pairing/
    │   ├── test_monrad.py
    │   └── test_dutch.py
    ├── tiebreakers/
    │   ├── test_buchholz.py
    │   ├── test_head_to_head.py
    │   └── test_stat_tiebreaker.py
    ├── test_advancement.py
    ├── test_unwind.py
    ├── test_placement.py
    ├── test_serialization.py
    ├── test_naming.py
    └── test_best_of.py
```

---

## Data Models

All models are Python `dataclass` instances. Use `@dataclass(frozen=False)` — the
immutability guarantee comes from the functional API returning new instances, not from
frozen dataclasses (which don't compose well with lists).

### `enums.py`

```python
class MatchStatus(Enum):
    PENDING    = 'pending'     # Waiting on a prior match to resolve
    READY      = 'ready'       # Both participants known, match can be played
    BYE        = 'bye'         # Auto-advance, no game played
    COMPLETED  = 'completed'   # Result reported

class BracketSide(Enum):
    WINNERS      = 'winners'
    LOSERS       = 'losers'
    GRAND_FINAL  = 'grand_final'

class AdvancementType(Enum):
    RESULT    = 'result'    # Normal match result
    BYE       = 'bye'       # Planned bye (no opponent)
    FORFEIT   = 'forfeit'   # Opponent no-showed or withdrew mid-match
    WALKOVER  = 'walkover'  # Opponent disqualified

class BracketState(Enum):
    DRAFT      = 'draft'      # TO still editing seeds/config, not started
    PUBLISHED  = 'published'  # Bracket locked, matches being played
    COMPLETE   = 'complete'   # All matches resolved

class PairingMethod(Enum):
    MONRAD = 'monrad'
    DUTCH  = 'dutch'
```

### `participant.py`

```python
@dataclass
class Participant:
    id: Any                              # Caller-defined. int, UUID, str — library is agnostic.
    seed: int                            # 1-indexed. Seed 1 = best.
    name: str
    stats: dict[str, Any] = field(default_factory=dict)
    # stats holds caller-defined values for tiebreakers, e.g.:
    # {'run_differential': 12, 'runs_scored': 45, 'glicko_rating': 1823}
```

### `match.py`

```python
@dataclass
class Match:
    id: int
    round_number: int
    bracket_side: BracketSide
    participant1_id: Any | None          # None = slot not yet filled (PENDING) or BYE
    participant2_id: Any | None
    winner_id: Any | None
    loser_id: Any | None
    advancement_type: AdvancementType | None
    next_winner_match_id: int | None     # Where winner advances to
    next_loser_match_id: int | None      # Where loser drops (double elim only)
    status: MatchStatus
    best_of: int = 1                     # BO1 default; TO can set per match or per round
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata: caller attaches game IDs, timestamps, scores, etc.
    # Library never reads metadata. It is returned as-is in unwind signals.
```

### `round.py`

```python
@dataclass
class Round:
    number: int
    bracket_side: BracketSide
    match_ids: list[int]
    name: str                            # Human-readable. See naming/round_names.py
    best_of: int | None = None           # If set at round level, overrides match defaults
```

### `bracket.py`

```python
@dataclass
class Bracket:
    format: str                          # 'single_elim', 'double_elim', etc.
    state: BracketState
    participants: list[Participant]
    matches: list[Match]
    rounds: list[Round]
    config: dict[str, Any]
    # config keys by format:
    #   single_elim:  third_place_match (bool)
    #   double_elim:  grand_final_reset (bool)
    #   swiss:        rounds (int), pairing_method (PairingMethod),
    #                 tiebreakers (list[str]), allow_bye (bool)
    #   pools:        num_pools (int), advancement_count (int),
    #                 bracket_format (str), snake_shuffle (bool)
    #   gauntlet:     style ('single' | 'dual'), opponent_choice (bool),
    #                 choice_scope ('round' | 'semifinals')
```

### `standing.py`

```python
@dataclass
class Standing:
    participant_id: Any
    rank: int
    wins: int
    losses: int
    advancement_type_counts: dict[AdvancementType, int]
    # Tracks how many results were by forfeit, walkover, bye, or normal result.
    # Callers can decide whether to include forfeits in win/loss display.
    tiebreaker_scores: dict[str, float]  # Keyed by tiebreaker class name
```

### `placement.py`

```python
@dataclass
class Placement:
    participant_id: Any
    position: int          # 1st, 2nd, 3rd, 4th, etc.
    position_label: str    # '1st', 'Top 4', 'Top 8', etc.
    eliminated_in: str     # Round name where participant was eliminated
```

---

## Public API

All of these are importable from the top-level `pybracket` package.

### Generation

```python
def generate_single_elim(
    participants: list[Participant],
    third_place_match: bool = False,
    protected_seeds: int = 0,        # Top N seeds guaranteed not to meet until their
                                     # natural round (e.g., 4 = top 4 can't meet until semis)
) -> Bracket

def generate_double_elim(
    participants: list[Participant],
    grand_final_reset: bool = True,
    protected_seeds: int = 0,
) -> Bracket

def generate_round_robin(
    participants: list[Participant],
    tiebreakers: list[Tiebreaker] | None = None,
) -> Bracket

def generate_swiss(
    participants: list[Participant],
    rounds: int | None = None,           # None → use recommend_swiss_rounds()
    pairing_method: PairingMethod = PairingMethod.DUTCH,
    tiebreakers: list[Tiebreaker] | None = None,
) -> Bracket

def generate_pools(
    participants: list[Participant],
    num_pools: int,
    advancement_count: int,              # Players advancing per pool
    bracket_format: str = 'double_elim',
    snake_shuffle: bool = True,          # Apply rematch-avoidance shuffle to snake seed
    tiebreakers: list[Tiebreaker] | None = None,
    **bracket_kwargs,                    # Passed to bracket generation (grand_final_reset, etc.)
) -> PoolsBracket                        # PoolsBracket wraps pool Brackets + elimination Bracket

def generate_gauntlet(
    participants: list[Participant],
    style: Literal['single', 'dual'],
    opponent_choice: bool = False,       # Higher seed can choose opponent each round
    choice_scope: Literal['round', 'semifinals'] = 'round',
) -> Bracket
```

### Result Reporting

```python
def report_result(
    bracket: Bracket,
    match_id: int,
    winner_id: Any,
    advancement_type: AdvancementType = AdvancementType.RESULT,
    metadata: dict | None = None,        # Caller attaches game ID, score, etc.
) -> Bracket                             # New bracket with updated state

def report_choice(
    bracket: Bracket,
    match_id: int,
    chosen_opponent_id: Any,             # Gauntlet opponent choice by higher seed
) -> Bracket

def unwind_result(
    bracket: Bracket,
    match_id: int,
) -> tuple[Bracket, list[UnwindSignal]]
# UnwindSignal: dataclass containing match_id and metadata of every match
# that was invalidated downstream. Caller uses this to scrub game records.
```

### Querying

```python
def get_ready_matches(bracket: Bracket) -> list[Match]
def get_standings(bracket: Bracket) -> list[Standing]
def get_placements(bracket: Bracket) -> list[Placement]
def is_complete(bracket: Bracket) -> bool
def get_winner(bracket: Bracket) -> Participant | None
def get_participant(bracket: Bracket, participant_id: Any) -> Participant | None
def get_match(bracket: Bracket, match_id: int) -> Match | None
```

### Swiss-specific

```python
def recommend_swiss_rounds(participant_count: int) -> int
# Returns ceil(log2(n)). Always provide this recommendation to the TO.

def advance_swiss_round(bracket: Bracket) -> Bracket
# Generates next round's pairings using the configured pairing method.
# Raises if current round is not fully complete.
```

### Reseeding

```python
def reseed(
    bracket: Bracket,
    new_seed_order: list[Any],           # participant_ids in new seed order
) -> Bracket
# Valid in DRAFT state (before bracket starts) or at pool → bracket transition.
# Raises BracketStateError if bracket is PUBLISHED and matches have been played.

def reseed_pools_to_bracket(
    pools_bracket: PoolsBracket,
    new_seed_order: list[Any] | None = None,  # None = use snake seeding result
) -> PoolsBracket
# Called after all pool matches complete, before elimination bracket starts.
# TO can pass a manual order or accept the library's snake seed.
```

### Best-of Configuration

```python
def set_best_of(
    bracket: Bracket,
    best_of: int,                        # Set globally
    round_overrides: dict[int, int] | None = None,  # {round_number: best_of}
) -> Bracket
# Can only be called in DRAFT state or before a round begins.
```

### Utilities

```python
def recommend_swiss_rounds(participant_count: int) -> int
def next_power_of_2(n: int) -> int
def recommend_pool_count(participant_count: int, target_pool_size: int = 4) -> int

# Serialization
def bracket_to_dict(bracket: Bracket) -> dict
def bracket_from_dict(data: dict) -> Bracket
def bracket_to_json(bracket: Bracket) -> str
def bracket_from_json(json_str: str) -> Bracket
```

---

## Format-Specific Implementation Notes

### Single Elimination

- Bracket size is always the next power of 2 above participant count.
- Bye assignment: top seeds receive byes. Seed 1 gets a bye before seed 2, etc.
- Standard seeding positions: 1 vs 2^n, 2 vs (2^n - 1), with bracket-optimized ordering
  ensuring the best seeds can only meet in the later rounds their seeding implies.
- Protected seeds: if `protected_seeds=4`, seeds 1–4 are guaranteed to be on different
  quarter-bracket paths so they cannot meet before the semifinals.
- Optional third-place match: losers of both semifinal matches play. Always the last match
  in the `rounds` list.
- `next_loser_match_id` is always `None` — there is no losers bracket.

### Double Elimination

- **Structure**: alternating rounds of incoming (WB losers merge with LB survivors) and
  survivors-only rounds.
- **Loser drop positions**: when a player loses in winners bracket round R, their slot in
  the losers bracket is calculated using the bracket-optimized placement algorithm to minimize
  the chance of an early rematch. Read `src/helpers.ts` from brackets-manager.js for the
  reference implementation of this placement logic before implementing.
- **Grand final reset**: always generate the reset match slot. If `grand_final_reset=True`,
  the reset match starts as `PENDING` and is activated (set to `READY`) if the losers bracket
  finalist wins the first grand final match. If `grand_final_reset=False`, the slot is
  generated but immediately skipped on losers finalist victory.
- **Placement**: loser of grand final = 2nd. Winner of losers final (who lost grand final) = 2nd
  if reset occurs and they win. Eliminated in losers R1 = last place band. Build placement
  bands by elimination round.
- **`get_ready_matches()`**: this was an open issue in brackets-manager.js for double elim.
  Implement it correctly from the start — a match is READY when both `participant1_id` and
  `participant2_id` are filled and `status == READY`.

### Round Robin

- Generate all pairings using the circle method (rotate all participants except the first
  each round). This is the standard O(n) round-robin pairing algorithm.
- If participant count is odd, one participant gets a bye each round (rotates through all).
- Standings order: wins first, then tiebreakers in configured order.
- Round robin is always fully generated at creation time (unlike Swiss).

### Swiss

- **Round count**: library recommends `ceil(log2(n))`. TO sets final count. Store in config.
- **Pairing methods** — TO chooses at generation time:
  - **Monrad**: pair by current standings, top vs top+1, etc. Simple, fast.
  - **Dutch (FIDE)**: implement per FIDE Handbook C.04.3. Handles floats, downfloats,
    color preferences (irrelevant for most games but structure is needed), and avoids
    rematches. This is the reference algorithm — implement it precisely per the handbook.
- **Odd player bye**: each round, the lowest-ranked player who has not yet received a bye
  gets one. Track bye history in `Standing`.
- **Rounds are generated lazily**: `advance_swiss_round()` generates the next round after
  the previous is complete. The `Bracket` accumulates rounds over time.
- **Tiebreakers**: implement Buchholz (sum of opponents' win counts) and truncated Buchholz
  (same but drop the lowest opponent score). Head-to-head as a secondary tiebreaker.
  `StatTiebreaker` for caller-defined stats.
- **No rematches**: both Monrad and Dutch implementations must guarantee no repeated pairings.
  Write explicit tests for this invariant at 4, 8, 16, and 32 players.

### Pools → Bracket

- **Pool assignment**: snake seeding. With 4 pools: seed 1→A, 2→B, 3→C, 4→D, 5→D, 6→C,
  7→B, 8→A, etc.
- **Rematch-avoidance shuffle**: after snake seeding, apply a shuffle within seed bands to
  ensure players from the same pool are placed on opposite sides of the elimination bracket
  wherever possible. TO can disable this or manually reseed at the transition.
- **Pool size**: if participants don't divide evenly, the library distributes extras to the
  earliest pools (pool A gets an extra before pool B). TO is notified of uneven sizes and
  can override.
- **Advancement**: after all pool matches complete, call `reseed_pools_to_bracket()`. Until
  then, the elimination bracket is in DRAFT state.
- **Pool tiebreakers**: pools use the same tiebreaker system as round robin.

### Gauntlet

- **Single-sided gauntlet**: completely linear chain. NOT a tree.
  - Match 1: seed N vs seed N-1
  - Match K: winner of match K-1 vs seed (N-K)
  - Final: last remaining challenger vs seed 1
  - Seed 1 plays exactly 1 match regardless of field size.
  - Seed 1 has a `next_winner_match_id` pointing to no prior match — they enter at the final.
  - Data model: use `round_number` to represent position in the chain. Each round has exactly
    one match.

- **Dual-sided gauntlet**: seeds 1 and 2 are placed at the top of each bracket half at the
  semifinal position. Lower seeds fill the earlier rounds.
  - With N participants, seeds 3–N play out the sub-bracket. Seeds 1 and 2 enter at semis.
  - Treat as a single-elim bracket where seeds 1 and 2 receive enough byes to reach the semis.
  - With odd lower-seed counts, standard bye rules apply.

- **Opponent choice** (if `opponent_choice=True`):
  - When `choice_scope='round'`: after each round, the higher seed may choose which opponent
    they face from among those who have advanced. Return a `ChoicePending` match status
    variant. Caller must invoke `report_choice()` before the match becomes READY.
  - When `choice_scope='semifinals'`: only the semifinal-stage opponents can be chosen.
  - This means some matches are not determined at generation time. The bracket has
    `PENDING_CHOICE` match slots. These cannot be unwound until the choice is made.

---

## Reseeding

Reseeding is supported in the following contexts:

1. **Pre-tournament (DRAFT state)**: full reseed of participant order at any time.
2. **Pools → bracket transition**: TO can manually override the snake-seed result before
   the elimination bracket is published.
3. **Mid-double-elim** (advanced, optional): reseeding at a defined round boundary in the
   winners bracket. This is complex — only support it if the bracket has not yet produced
   any results in the affected round. Raises `ReseedError` if reseeding would conflict with
   completed matches.

---

## Unwind / Result Correction

When `unwind_result(bracket, match_id)` is called:

1. The match's result is cleared. `winner_id`, `loser_id`, `advancement_type` set to `None`.
   Status set back to `READY`.
2. The library walks forward through `next_winner_match_id` and `next_loser_match_id` chains.
3. Every downstream match that had a participant placed by the unwound result is also cleared
   back to `PENDING` or `READY` as appropriate.
4. For every match cleared, its `metadata` dict is included in the returned `UnwindSignal`
   list. This allows the caller to know exactly which game records need to be scrubbed.
5. If a downstream match was itself already reported, its result is also unwound (cascading).
   The full cascade is returned in the `UnwindSignal` list.
6. The grand final reset match (if activated by the unwound result) is deactivated and set
   back to `PENDING`.

```python
@dataclass
class UnwindSignal:
    match_id: int
    metadata: dict[str, Any]    # Contains whatever the caller attached (e.g., game_id)
```

---

## Bye / Forfeit / Walkover Distinction

These are tracked separately via `AdvancementType` on each `Match`:

| Type | Meaning | Counts as win? |
|---|---|---|
| `RESULT` | Normal match played | Yes |
| `BYE` | No opponent existed at generation time | No (excluded from record) |
| `FORFEIT` | Opponent no-showed or withdrew mid-match | Yes (win by forfeit) |
| `WALKOVER` | Opponent disqualified | Yes (win by walkover) |

`Standing.advancement_type_counts` tracks how many of each type a participant has received.
Callers decide how to display or weight these — the library never hides them.

---

## Round Naming

`naming/round_names.py` generates human-readable names based on matches remaining.

Rules:
- Last match: `"Grand Final"` (or `"Final"` for single-sided gauntlet)
- Second to last in winners: `"Winners Semifinals"` / `"Losers Finals"` etc.
- Near-end rounds get named: `"Grand Final Reset"`, `"Losers Finals"`,
  `"Winners Finals"`, `"Semifinals"`, `"Quarterfinals"`
- Earlier rounds: `"Winners Round 1"`, `"Losers Round 3"`, `"Round 2"`, etc.
- Swiss rounds: `"Round 1"`, `"Round 2"`, ..., `"Final Round"`
- Pool rounds: `"Pool A — Round 1"`, etc.

---

## Best-of Configuration

- Default is BO1 (each match is decided by a single game).
- `set_best_of(bracket, best_of=3)` sets all matches to BO3.
- `round_overrides={5: 5, 6: 5}` sets specific rounds to BO5 (e.g., semis and finals).
- Match-level `best_of` always takes precedence over round-level, which takes precedence
  over bracket-level.
- The library tracks `best_of` on the `Match` but does **not** track individual game scores
  within a match. That is the caller's responsibility (via `metadata`). The library only
  knows the final winner of a match.

---

## Placement Calculation

Final placements are computed from bracket structure by `get_placements()`:

- **Single elim**: placement by elimination round. Losing in round R gives a placement band.
  - Loser of final: 2nd
  - Losers of semis: 3rd/4th
  - Losers of quarters: 5th–8th, etc.
- **Double elim**: losers bracket elimination determines placement band. Loser of grand
  final (or grand final reset if it occurs) is 2nd regardless of bracket side.
- **Round robin / Swiss**: rank by final standings position.
- **Consolation matches** (if enabled): 3rd place match loser is 4th, winner is 3rd.
  5th/7th place matches follow the same logic.

---

## Serialization

All `Bracket` instances must round-trip cleanly to and from JSON with no data loss.
`bracket_to_dict()` / `bracket_from_dict()` handle nested dataclass serialization.
`Enum` values are serialized as their `.value` string. `Any`-typed IDs are preserved as-is.

Write explicit round-trip tests for every format in `test_serialization.py`.

---

## Testing Strategy

### General Rules

- Every public function has at least one happy-path test and one edge-case test.
- All bracket generation functions are tested at: 2, 3, 4, 5, 8, 16, and 32 participants.
- Use `pytest.fixture` for common participant lists in `conftest.py`.
- Use `hypothesis` for property-based tests on pairing algorithms and seeding.
- Port tests from `brackets-manager.js` test suite, translating JS to pytest.
  Comment each ported test with `# Ported from brackets-manager.js test/<file>.spec.js`.

### Format Tests (`tests/formats/`)

Each format test file must cover:
- Correct number of matches generated (single elim: `2^ceil(log2(n)) - 1`, etc.)
- Correct number of rounds
- All BYEs placed correctly (top seeds receive byes)
- `get_ready_matches()` returns correct matches at each stage
- `is_complete()` returns `False` mid-tournament, `True` at end
- `get_winner()` returns correct participant
- Full tournament simulation (report all results, verify placements)

### Double Elimination Specific

- Verify loser drop positions are bracket-optimized (no immediate rematches in losers R1)
- Grand final reset activates when losers finalist wins first set
- Grand final reset is skipped when winners finalist wins first set
- Placement bands computed correctly for 8 and 16 player brackets
- `get_ready_matches()` works correctly at all stages (this was a known bug in brackets-manager.js)

### Swiss Specific

- No rematches across all rounds at 4, 8, 16, 32 players (invariant test)
- Dutch pairing output matches FIDE handbook example pairings where provided
- Odd player bye rotates correctly — same player never gets two byes
- `recommend_swiss_rounds(n)` returns `ceil(log2(n))` for all n 2–256
- Buchholz scores computed correctly against hand-verified examples

### Pairing Tests (`tests/pairing/`)

- Test Dutch pairing against the specific examples in FIDE C.04 handbook.
  Comment these tests with: `# Source: FIDE Handbook C.04.3, Example N`
- Test Monrad pairing for correctness at 4, 8, 16 players
- Both methods: verify no rematches, verify pairing by score groups

### Unwind Tests (`tests/test_unwind.py`)

- Unwind a result with no downstream matches
- Unwind a result that has one downstream match (not yet played)
- Unwind a result that has one downstream match (already played) — cascade
- Unwind a result that cascades 3 levels deep
- Verify `UnwindSignal` list contains correct metadata from all cleared matches
- Verify bracket is in valid playable state after unwind

### Serialization Tests (`tests/test_serialization.py`)

- Round-trip every format at 8 participants: `bracket == bracket_from_dict(bracket_to_dict(bracket))`
- Round-trip mid-tournament (some results reported)
- Round-trip completed tournament
- Verify `Any`-typed IDs survive serialization for `int`, `str`, and `uuid.UUID`

### Property-Based Tests (hypothesis)

In `conftest.py`, define hypothesis strategies for generating valid participant lists.
Use them in:
- `test_seeding.py`: top seed always placed at position 1 in bracket
- `test_single_elim.py`: match count always `2^ceil(log2(n)) - 1`
- `test_double_elim.py`: every non-bye participant plays at least 2 matches before elimination
- `test_swiss.py`: no repeated pairings across any tournament simulation

---

## Coding Standards

- **Python version**: 3.10 minimum. Use `match` statements, `X | Y` union types.
- **`from __future__ import annotations`** in every file.
- **`__all__`** defined in every `__init__.py`. Only export what is intentionally public.
- **No global state**. All functions are pure (input → output, no side effects).
- **Docstrings**: one-line summary on all public functions. No multi-paragraph docstrings.
  Parameters are self-documenting via type hints.
- **Comments**: only when the WHY is non-obvious (a specific FIDE rule, a non-intuitive
  algorithm step, a ported test source). Never describe what the code does.
- **Error handling**: raise specific exceptions from `errors.py`:
  - `BracketStateError` — operation not valid in current bracket state
  - `MatchNotFoundError` — match_id not in bracket
  - `ParticipantNotFoundError` — participant_id not in match
  - `InvalidResultError` — winner_id not a participant in the match
  - `ReseedError` — reseeding conflict with completed matches
  - `SwissRoundIncompleteError` — `advance_swiss_round()` called before current round done
- **`pyproject.toml`**: use `[project]` table, not `setup.py`. Dev dependencies under
  `[project.optional-dependencies]`. Configure `mypy` in strict mode and `ruff` in
  `[tool.ruff]`.

---

## License

`LICENSE` must contain two MIT copyright notices:

```
MIT License

Copyright (c) [year] [ProjectRio authors]

Copyright (c) 2020 Corentin Girard (brackets-manager.js)
https://github.com/Drarig29/brackets-manager.js

Permission is hereby granted...
```
