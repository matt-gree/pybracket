# Multi-stage tournaments — design

Status: **spine implemented** (core `Tournament`/`Phase` engine + tests landed; see
"Implementation status" below). Target: a single umbrella that chains arbitrary
phases of different formats — pools→pools→bracket, pools→qualifier→final, Swiss→top-cut,
and the high-pool / low-pool merge from
[Slice 2024 "Stars Off"](https://www.start.gg/tournament/slice-2024/event/stars-off/).

### Implementation status

Landed (`pybracket/models/tournament.py`, `pybracket/tournament.py`, serialization, tests in
`tests/test_tournament.py`, 16 cases):

- `SlotRef` / `Qualification` / `Phase` / `Tournament` / `PhaseSpec` / `Ranked` models, with
  the `ALL_PLACES` (place=0) and `EACH_GROUP` (group=-1) sentinels.
- `generate_tournament` (validates unique ids + acyclic earlier-only references; builds phase 0
  live, others empty/`DRAFT`).
- Lifecycle: `draft_phase` (with `new_seed_order` override), `preview_phase` (placeholders),
  `publish_phase`, `revert_phase`, `advance_phase`; plus `phase_results`, `phase_is_complete`,
  `is_phase_draftable`.
- Constructors `all_of` / `top` / `top_of_each_group` / `places` / `place` (spec string
  `"phase"` or `"phase#group"`).
- Merge seeding via the existing `qualifier_seed_order` (rank / snake / manual); same-source
  rematch repair applies only at a real merge (>1 source).
- `groups` works for **any** format (verified: `single_elim, groups=4` wave brackets).
- `tournament_to_dict/from_dict` + json round-trip.
- **`PoolsBracket` removed** (done): `formats/pools.py` deleted, `BracketFormat.POOLS` dropped,
  `tests/formats/test_pools.py` ported to the 2-phase `Tournament` shape, README + SPEC updated.
- **Truncation / early-stop** (done): single-elim qualifier brackets via `survivors=N` (§16).
- **Advancement-aware unwind gate** (done): `edit_phase_result` / `unwind_phase_result` /
  `edit_changes_advancement` / `dependent_phases` (§11).
- **`state=` on `generate_swiss` / `generate_gauntlet`** (done): both now take
  `state: BracketState = PUBLISHED` and pass it to the `Bracket` constructor (threaded through
  the gauntlet build chain), so a downstream Swiss/gauntlet phase builds `DRAFT` directly
  instead of the old post-build `bracket.state` mutation in `_build_one` (§13).

The multi-stage feature is complete. Every spine/follow-up item above is implemented and
tested (687 tests; mypy strict + ruff clean; 98% line coverage on the new/changed modules,
the remainder being defensive guards).

## 1. Motivation

Today `PoolsBracket` ([formats/pools.py](pybracket/formats/pools.py)) is a *hardcoded
two-phase tournament*: `pools: list[Bracket]` (round robin) feeding `elimination: Bracket`,
with `config` describing the handoff. Its lifecycle —
`draft_pools_to_bracket` → `preview_pools_bracket` → `publish_bracket` — is exactly a
**phase-boundary lifecycle**: gather upstream results, build the downstream bracket in
`DRAFT`, let the TO review/reorder, then flip to `PUBLISHED`. The placeholder qualifier
`_placeholder("Pool A #1", origin_pool=…, origin_place=…)` is already an abstract
*reference to a not-yet-decided finisher*.

This proposal lifts those two hardcoded phases into an **ordered list of phases** and makes
the wiring between them a first-class object. It is an evolution of the existing pools
machinery, not a rewrite — `PoolsBracket` becomes one shape a `Tournament` can take.

### Goals

- Chain N phases of heterogeneous formats under one umbrella.
- Wire any phase's *output positions* into any later phase's *entrants* (supports
  many-to-one merges and one-to-many splits).
- Per-source advancement so "high pool seeds everyone, low pool cuts to top-4" is expressible
  — and it lives in the *downstream* `Qualification` (the consumer decides how many it pulls),
  not as a property of the upstream phase.
- Per-phase records stay independent. A tournament-total record is the **sum of phase records**
  via the query API; no result carries forward to change a later phase's outcomes.
- Reuse the draft / preview / publish lifecycle at every boundary.
- Preserve library principles: storage-agnostic, immutable-ish returns, library-recommends /
  TO-overrides, zero runtime deps.

### Non-goals (v1)

- **Carrying match records across a boundary** (Swiss points into a continued Swiss, "soft
  reset" top-cuts). v1 carries *seeding only*, matching today's pools. See §11.
- Mid-phase re-pairing that depends on another phase's live state.

## 2. Conceptual model

```
Tournament (umbrella)
  └── phases: [Phase, Phase, …]          ordered, topologically sorted
        each Phase:
          ├── format            round_robin | swiss | single_elim | double_elim | gauntlet
          ├── groups            1 (single bracket) or N parallel sub-brackets — ORTHOGONAL to
          │                     format: round_robin×N = pools, single_elim×N = wave/bracket-pools
          ├── entrants          None (phase 0, seeded from the tournament field) OR a Qualification
          ├── brackets          list[Bracket]   (1 for groups=1, N for grouped)
          └── state             DRAFT | PUBLISHED | COMPLETE
```

Phases are connected by **slot references**, not by participants. A phase exposes a ranked
output addressable as `(phase_id, group, place)`; a later phase names its entrants as a list
of those addresses. The reference resolves to a concrete participant only once the source
phase is `COMPLETE`.

This single indirection yields the whole DAG for free:

- **Linear chain** — phase *k*'s entrants reference phase *k-1*.
- **Many-to-one merge** — entrants pull from several sources (high pool + low pool → top cut).
- **One-to-one split** — a championship phase pulls places 1–4, a consolation phase pulls 5–8.

## 3. New primitive: the slot reference

```python
@dataclass(frozen=True)
class SlotRef:
    """A reference to a ranked finishing position of an upstream phase."""
    phase: str                  # source phase id
    place: int                  # 1-based finishing position
    group: int | None = None    # which group/pool within the phase, or None = overall standing
```

This is the promotion of pools' `_placeholder` to a first-class, serializable object. When a
source phase completes, a `SlotRef` resolves to a `Participant`; before that, it renders as a
named placeholder ("Pool A #1", "Swiss #3") for previews.

Convenience constructors (the ergonomic surface — authors rarely write `SlotRef` by hand):

```python
def all_of(phase: str) -> list[SlotRef]              # every finisher, seed-only
def top_of_each_group(phase: str, n: int) -> list[SlotRef]   # top-n of every group
def places(phase: str, lo: int, hi: int, group=None) -> list[SlotRef]
def place(phase: str, p: int, group=None) -> SlotRef
```

## 4. The wiring: `Qualification`

A boundary needs both *which* slots and *how they seed* into the target:

```python
@dataclass
class Qualification:
    sources: list[SlotRef]        # ragged is fine: 8 from high + 4 from low
    seeding: str = "snake"        # 'snake' | 'rank' | 'manual'  (library recommends; TO overrides)
```

`seeding`:

- `rank` — global rank-major order (all #1s, then all #2s, …), source order breaking ties.
- `snake` — `rank` plus the deeper-band rotation and same-source rematch-avoidance repair
  that `pool_seeding.qualifier_slot_order` already implements, generalized from "same pool"
  to "same source phase/group".
- `manual` — preserve `sources` order verbatim; the TO owns it (used after a `draft_phase`
  reorder).

## 5. Containers and public API

```python
@dataclass
class Phase:
    id: str
    format: str
    config: dict[str, Any]                       # the format's own kwargs
    entrants: Qualification | list[Participant]  # list = phase 0 (seeded from the field)
    groups: int = 1
    group_assignment: str = "snake"              # how entrants split into groups (pools)
    brackets: list[Bracket] = field(default_factory=list)
    state: BracketState = BracketState.DRAFT

@dataclass
class Tournament:
    phases: list[Phase]
    participants: list[Participant]
    config: dict[str, Any] = field(default_factory=dict)
```

Authoring uses a lightweight spec; phase 0 is built live, the rest start empty/`DRAFT`:

```python
t = generate_tournament(
    participants,
    phases=[
        # A grouped round-robin phase = two pools. No advancement count here:
        # who advances is decided by the next phase's Qualification.
        PhaseSpec("groups", "round_robin", groups=2),
        PhaseSpec("cut", "double_elim",
                  entrants=Qualification(
                      sources=all_of("groups#0") + top_of_each_group("groups#1", 4),
                      seeding="snake")),
    ],
)
```

Operations are the pools functions, generalized to take a target phase id. **Result
reporting does not change** — you drive each phase's `Bracket` with the existing
`report_result` / `advance_swiss_round`; only boundaries get new functions (exactly how pools
works today). Every operation returns a new `Tournament` (immutable-ish).

| Today (hardcoded 2-phase)          | Generalized                                  |
| ---------------------------------- | -------------------------------------------- |
| `generate_pools(...)`              | `generate_tournament(participants, phases=…)`|
| `draft_pools_to_bracket(pb, seed)` | `draft_phase(t, phase_id, new_seed_order=None)` |
| `preview_pools_bracket(pb)`        | `preview_phase(t, phase_id)`                 |
| `publish_bracket(pb)`              | `publish_phase(t, phase_id)`                 |
| `reseed_pools_to_bracket(pb)`      | `advance_phase(t, phase_id)` (draft+publish) |
| —                                  | `revert_phase(t, phase_id)` (tear back to DRAFT) |
| —                                  | `phase_results(t, phase_id) -> list[Ranked]` |

`phase_results` dispatches like `get_placements` already does
([advancement/placement.py:34](pybracket/advancement/placement.py:34)): grouped/round-robin/
swiss phases rank by `get_standings`, elimination phases by `get_placements`. That is the
function that resolves `SlotRef`s.

## 6. Phase lifecycle and readiness

Per-phase state reuses `BracketState` (`DRAFT` → `PUBLISHED` → `COMPLETE`).

- A phase is **draftable** iff every phase named by its `entrants` `SlotRef`s is `COMPLETE`.
- `draft_phase` resolves sources → seed order (per `Qualification.seeding`) → builds the
  phase's bracket(s) in `DRAFT`. `new_seed_order` overrides, flipping `seeding` to `manual`.
- `preview_phase` does the same with placeholder qualifiers and never requires sources to be
  played — it can cascade through *all* downstream phases for a full bracket preview.
- `publish_phase` re-settles and flips `DRAFT` → `PUBLISHED`.
- A phase becomes `COMPLETE` when `is_complete` holds for all its brackets, unlocking its
  dependents.

```
            sources COMPLETE
   (empty) ─────────────────▶ DRAFT ──publish_phase──▶ PUBLISHED ──all matches──▶ COMPLETE
      ▲        draft_phase      │                                                     │
      └──────────────────────── revert_phase ◀──────────────────────────────────────┘
```

## 7. Seeding at a merge

The default merge-seed is a small generalization of the existing pools seeder, **not** a
new algorithm. `qualifier_seed_order`
([seeding/pool_seeding.py:49](pybracket/seeding/pool_seeding.py:49)) already tolerates ragged
sources via `if rank < len(ranked_by_pool[pool])`. Feed it one ranked list per source:

```
sources  = [[H1..H8], [L1..L4]]           # high pool contributes 8, low contributes 4
advancement_count = max(len(s) for s in sources)   # = 8
qualifier_seed_order(sources, 8, snake_shuffle=True)
#  band 0: H1, L1   band 1: H2, L2 … band 3: H4, L4   band 4: H5 (low exhausted) … band 7: H8
```

Two generalizations to the existing code:

1. The rematch-avoidance repair (`_repair_first_round`) keys on "same source phase/group"
   instead of "same pool" — same logic, broader notion of provenance.
2. Source order is the priority used to break ties within a band (high pool ahead of low).

Whatever the default produces, the `DRAFT` → reorder → `publish` escape hatch lets the TO fix
it — the principle the library already follows.

## 8. Worked examples

("pools" below means a grouped round-robin phase — `round_robin, groups=N` — per §12.)

| Format the TO wants                  | Phases                                       | Key wiring |
| ------------------------------------ | -------------------------------------------- | ---------- |
| Pools → pools → bracket              | `[round_robin×g, round_robin×g, double_elim]`| each boundary `top_of_each_group(prev, n)` |
| Pools → qualifier → final            | `[round_robin×g, single_elim, double_elim]`  | final pulls qualifier top-k; *optionally* a consolation phase pulls the rest (one-to-many) |
| Swiss → top cut                      | `[swiss, single_elim]`                       | `places("swiss", 1, 8)` |
| **High / low pools → top cut**       | `[round_robin×2, double_elim]`               | `all_of("groups#0") + top_of_each_group("groups#1", 4)` |

The high/low asymmetry needs no special phase config: both pools are an ordinary
`groups=2` round-robin phase, and the difference ("high seeds everyone, low cuts to top-4")
is expressed entirely in the top-cut phase's `Qualification.sources` —
`all_of` the high group, `top_of_each_group(…, 4)` the low. The consumer decides who advances.
(Two separate single-group phases merging is equivalent and equally valid.)

## 9. Serialization

`Tournament` round-trips by extending the existing `bracket_to_dict` machinery
([utils/serialization.py](pybracket/utils/serialization.py)):

```
{ "participants": [...], "config": {...},
  "phases": [ { "id", "format", "config", "groups", "group_assignment", "state",
                "entrants": <seed list | Qualification dict>,
                "brackets": [ <bracket_to_dict> ... ] } ] }
```

`SlotRef` and `Qualification` are flat dataclasses — trivial to (de)serialize. This keeps the
Pyodide Bracket Studio bridge able to persist a whole tournament as one JSON blob.

## 10. Validation rules

- Phase ids unique; `Qualification` sources reference only **earlier** phases (topological,
  acyclic — enforced at `generate_tournament`).
- A `SlotRef.place` must be ≤ the source group's resolvable size; `group` must exist. (This
  is where the old `generate_pools` "advancement ≤ pool size" check now lives — per slot ref.)
- A phase's resolved entrant count must satisfy its format's constraints (e.g. ≥ 2).

## 11. Cross-phase edit / unwind policy

Decision: **lock upstream while a dependent is live — but only force a reset when advancement
actually changes.** The TO has ultimate authority between phases; the engine's job is to tell
them when a correction invalidates downstream play, not to babysit it.

When a result in a `COMPLETE` source phase is unwound or edited, recompute that phase's
resolved qualifier set and seeding for each dependent and compare:

- **Advancement unchanged** — a metadata-only edit, or a result that reorders only
  non-qualifiers, or one that leaves every qualifier and its seed identical → dependents stay
  intact. The source's per-phase record updates; nothing downstream moves.
- **Advancement changed** — a different participant qualifies, or a qualifier's seed into a
  dependent shifts → the affected dependent phases must be reverted with `revert_phase` (back
  to empty/`DRAFT`) before the source edit is accepted. No silent cascade through played-out
  brackets.

`revert_phase` is the explicit teardown valve. This generalizes today's pools invariant
("all sources complete before drafting") and keeps corrections honest.

**Implemented.** Two guarded operations + a query realize this:

- `edit_phase_result(t, phase_id, match_id, new_winner_id, *, group=0, …)` — unwind + re-report
  a corrected result. It recomputes each *live* dependent's resolved qualifiers/seeding before
  and after the edit (via `_resolve`); if any changes (a different qualifier, or a qualifier's
  seed shifts) it raises and names the phases to `revert_phase` first. An advancement-neutral
  edit (only non-qualifiers reorder, or a no-op) is applied with dependents left intact. The
  corrected result must keep the source complete (else all live dependents are flagged).
- `unwind_phase_result(t, phase_id, match_id, *, group=0)` — a *pure* unwind (leaves the source
  incomplete). Refused while any dependent is live, since it always strands what was drafted
  from the source; revert dependents first, or use `edit_phase_result`.
- `edit_changes_advancement(...)` / `dependent_phases(t, id, *, transitive=, live_only=)` —
  side-effect-free queries (a UI can preview the revert set before committing).

The blocked set returned is the changed dependents *plus everything live transitively below
them*, so the TO reverts the whole stranded subtree in one pass. Tests: the §11 block in
`tests/test_tournament.py` (neutral edit keeps dependents; advancement-changing edit and pure
unwind are blocked; revert unblocks both).

## 12. No `PoolsBracket` — decompose, don't wrap

`PoolsBracket` does **not** survive into this model. It is the only multi-phase composite the
library blesses today, and once `Tournament` exists, singling out pools→bracket is arbitrary
special-casing — why bless it but not Swiss→cut or pools→pools? Keeping it means two parallel
code paths (its bespoke draft/publish vs. the generic phase ops) that drift, two test
surfaces, and two ways to express one thing. Good practice favors one orthogonal primitive.
No backwards-compatibility shim is kept (the frontend will be updated to the new API).

Decompose it into its genuinely reusable parts, which **do** stay:

- **The pools *format*** — but only as a *grouped round-robin phase*
  (`format="round_robin", groups=N`). It is the parallel groups **only**; the elimination it
  used to bundle is now just the next phase. `groups` is orthogonal to format (grouped Swiss
  pods, wave brackets are the same mechanism), so "pools" need not be a distinct format at all.
- **The pool-seeding algorithms** — `seeding/pool_seeding.py` (snake assignment, qualifier
  seeding, rematch repair) is reusable domain logic, not a preset. It powers the grouping step
  and the snake `Qualification.seeding`.

What goes: the `PoolsBracket` dataclass and its five functions (`generate_pools` /
`draft_pools_to_bracket` / `preview_pools_bracket` / `publish_bracket` /
`reseed_pools_to_bracket`), fully subsumed by `generate_tournament` + the generic phase ops.

The pools→bracket **shortcut** ("give me a 2-phase pools tournament in one call") is a *recipe,
not a library type*. It lives in the frontend bridge (or an `examples/` recipe) and, if
offered, returns a plain `Tournament` — never a new type.

## 13. Required engine changes

- **`state=DRAFT` on every generator.** `build_single_elim`, `build_double_elim`, and
  `generate_round_robin` already accept `state`; `generate_swiss` and `generate_gauntlet`
  do not. They need the same plumbing (build without settling until `publish_phase`) so any
  format can be a non-leaf phase target. (Lower priority for formats only ever used as the
  first phase.)
- **A `_build_phase_bracket(format, entrants, config, groups, state)` dispatcher**, the
  generalization of `pools._build_elimination`, routing to each format's generator.
- **`phase_results` dispatcher** wrapping `get_standings` / `get_placements`.

## 14. Testing plan

- `SlotRef` resolution: overall vs per-group, before/after completion (placeholder vs real).
- Merge seeding: equal sources, ragged sources, same-source rematch avoidance, manual override.
- Lifecycle: draftable gating, draft→publish→complete, preview cascade with placeholders.
- Unwind policy: metadata/non-qualifier edit leaves dependents intact; a qualifier/seed change
  requires reverting dependents first, and is rejected until they are reverted.
- Serialization round-trip of a full multi-phase tournament.
- End-to-end: each of the four §8 examples plus the high/low merge, played to a champion.
- Port `tests/formats/test_pools.py` to the 2-phase `Tournament` shape (no `PoolsBracket`),
  proving the decomposition preserves the snake-seed and qualifier behaviour.

## 15. Resolved decisions

1. **Double-entry guard — none needed.** A participant may appear in two downstream phases
   (championship + redemption, etc.). Records are per-phase and never carry forward to change
   results, so there is nothing to corrupt; a tournament-total is the sum of phase records via
   `phase_results`. No validation guard.
2. **Full DAG** — confirmed. Many-to-one merges and one-to-many splits are both first-class.
3. **TO has ultimate authority between phases** — confirmed; the engine only gates resets when
   advancement actually changes (§11).
4. **Naming: `Phase`** — matches start.gg vocabulary and disambiguates from the in-bracket
   "stage"/round usage already in SPEC.md.

### Still open

- **Record carry-over** (§1 non-goal) — explicitly deferred. A future design could seed a
  phase's matches with prior wins/points, but v1 is seed-only.

## 16. Stopping a phase at top-N

A phase need not run to a single champion. Two separate mechanisms, only one of which is new:

- **Cut (downstream selection)** — the phase plays to its *natural* end and the next phase
  pulls top-N via `Qualification`. Works for **every** format: round-robin / Swiss expose a
  full ranking; elimination exposes one via `get_placements`. This already covers
  Swiss→top-cut, pools→bracket, pools→pools — no new code beyond the spine. "Stop a Swiss at
  top-N" is just its round count plus a downstream cut.
- **Truncation (early stop)** — the bracket itself ends before crowning a champion: a
  single-elim played *down to N survivors* who then switch into a different phase (a
  "qualifying bracket"). Well-defined only for **single_elim**, and only where N is a
  power-of-two round boundary (the "neatly resolvable" constraint, validated). The N survivors
  advance as equal-ranked qualifiers (ordered by original seed). `double_elim`/`gauntlet` have
  no clean mid-run top-N, so they run to completion and you cut from placements.

A phase with no dependents is simply **terminal** — the tournament ends there.

**Implemented.** `build_single_elim(..., survivors=N)` / `generate_single_elim(..., survivors=N)`
build a truncated bracket: `build_standard_bracket` gained a `max_rounds` cap, so only the
rounds needed to leave `N` co-survivors are emitted (their matches have no next pointer).
`survivors` must be a power of two with `2 <= survivors < field`, requires a power-of-two field
(no byes), and is incompatible with `third_place_match` / `bye_rounds` / `protected_seeds`. The
bracket records `config["truncated_to"] = N`; `get_winner` returns `None` for it, and a
dedicated `_truncated_placements` ranks the survivors at the top (`"Top N"`, ordered by seed)
with everyone else placed by the round they lost. In a `Tournament`, set it via the phase
`config` (`PhaseSpec("qual", "single_elim", config={"survivors": 8})`); the downstream phase
pulls the survivors with `top("qual", 8)`. Tests: `tests/formats/test_truncation.py` +
`test_qualifier_bracket_to_final`. `double_elim`/`gauntlet` truncation remains out of scope.
