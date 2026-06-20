# Scoring, series & tiebreakers — design

Status: **implemented** (2026-06-19). A **library-wide** layer (every format, not leagues) for:

1. **Per-game best-of series** — track each game of a BO-N match, not just the series winner.
2. **Caller-defined stat accumulation** — per-game/per-match numeric tallies the engine sums
   and re-derives, with the library staying fully game-agnostic.
3. **A configurable tiebreaker chain** — the caller owns the *inputs*, *aggregations*, and
   *priority order*; the library owns the arithmetic and a few built-in derived inputs.
4. **Draws** and an optional **points system** for standings-based formats.

Leagues ([LEAGUES_DESIGN.md](LEAGUES_DESIGN.md)) and multi-stage
([MULTISTAGE_DESIGN.md](MULTISTAGE_DESIGN.md)) consume this; nothing here is league-specific.

## 1. Principle: the library names no stat

The library is game-agnostic. It must never hardcode "runs", "goals", "maps". So the split is:

- **Caller owns the nouns and the policy** — the stat *names* (`"runs"`), which inputs to break
  ties on, which **aggregation** of each (for / against / differential), and the **explicit
  priority order**.
- **Library owns the arithmetic** — accumulating per-game/per-match contributions into totals,
  the standard aggregations, a handful of **built-in derived inputs** it can compute from
  results alone (match wins/losses, games won/lost), and re-deriving everything on edit/unwind.

`"runs"` is an opaque key to the library; `AccumulatedTiebreaker("runs", "diff")` means "sum
each team's `runs` and their opponents' `runs`, rank by the difference" — the library never
learns what a run is.

## 2. Per-game best-of series

Today a `Match` has `best_of: int` and a single winner; a BO3 is reported with one
`report_result`. Real series need each game (tennis sets, esports maps, a doubleheader), and
per-game stats. This is **library-wide** — any format can use BO-N.

```python
@dataclass
class Game:
    number: int                                   # 1-based within the match
    winner_id: Any | None                          # None = drawn game (only if draws allowed)
    loser_id: Any | None
    stats: dict[str, dict[Any, float]] = {}        # per-game contributions, keyed by stat then id
    metadata: dict[str, Any] = {}                  # caller's per-game scratch (engine ignores)

# Match gains:
#   games: list[Game] = []      # the series log; empty for a match reported match-level
```

Reporting:

- `report_game(bracket, match_id, winner_id, *, stats=None, draw=False, metadata=None) -> Bracket`
  appends a game. When a side reaches the clinch count (`best_of // 2 + 1`), the engine sets the
  match's `winner_id`/`loser_id`, marks it `COMPLETED`, and advances — exactly the existing
  `report_result` advancement, just deferred until the series is decided.
- `report_result(bracket, match_id, winner_id, …)` stays as the **match-level shortcut** (BO1,
  or when you don't track games): it records the decisive outcome directly with no game log.
- `unwind_game(bracket, match_id)` removes the last game (correct a single game mid-series);
  `unwind_result` clears the whole match (and its games) and cascades, as today.

Series score and decisions:

- `Match.series_score -> (int, int)` = games won by participant1/participant2, derived.
- **Odd `best_of`** always clinches. **Even `best_of`** (e.g. a two-leg series) can end level →
  a **match draw**, allowed only where draws are enabled (§5); otherwise the engine refuses to
  let the series end level and the caller must add a decider.
- A knockout (elimination) match must produce a winner; a level even-BO series there is a
  validation error (add a tiebreak game) — draws are only meaningful for standings formats.

## 3. Stat contributions

Per-game stats live on `Game.stats`; a match reported match-level can carry `Match.stats` (same
shape). Both are **blessed channels the ranking engine reads** — distinct from `metadata`,
which it never reads.

```
game.stats  = {"runs": {p1: 7, p2: 3}, "hits": {p1: 11, p2: 6}}   # per game
match.stats = {"runs": {p1: 12, p2: 9}}                            # when no game log is kept
```

The caller passes them when reporting: `report_game(..., stats={"runs": (7, 3)})` — a 2-tuple is
sugar ordered `(participant1, participant2)`; the general form is the per-id dict (for matches
that aren't 1v1 later).

## 4. Accumulation

`StandingsContext` (already the precomputed win/loss/H2H structure) gains accumulation, summed
across all of a participant's games and matches:

- **Built-in derived inputs** (computed from results, no caller stats needed):
  `wins` / `losses` (match/series level), `games_won` / `games_lost` (from the game logs),
  `draws`, and `points` (if a `PointsSystem` is set, §5).
- **Caller inputs** (from `stats`): for each name, `stat_for[pid][name]` (the team's own values)
  and `stat_against[pid][name]` (opponents' values in shared games/matches), plus a `count` for
  averages.

Everything rankable is thus one shape — an accumulator over per-game/per-match contributions —
which is why win-count, game-differential, and run-differential are the *same* mechanism.

## 5. Draws and points (standings formats)

- `AdvancementType.DRAW`; `report_draw(bracket, match_id, stats=None)` for a drawn match;
  `Standing` gains `draws` and `points`.
- Optional `PointsSystem(win=3, draw=1, loss=0, draws_allowed=True)` in the bracket/phase config.
  No points system → rank by record (today's behaviour). With one → standings rank by `points`,
  then the tiebreaker chain.
- Draws are valid only for standings formats and only when `draws_allowed`; elimination refuses
  them (§2).

## 6. The tiebreaker chain — caller-owned

One handler already exists: the `Tiebreaker` protocol + the single chain in `get_standings`,
used by every standings phase. We add **one generic accumulator tiebreaker**; the caller
assembles the chain in explicit priority order, mixing built-in and custom inputs and choosing
each one's aggregation:

```python
@dataclass(frozen=True)
class AccumulatedTiebreaker:
    input: str                 # built-in ("wins","games","draws","points") or a caller stat name
    agg: str = "diff"          # 'for' | 'against' | 'diff' | 'count' | 'avg'
    higher_is_better: bool = True

# Caller sets inputs, aggregations, and order explicitly:
tiebreakers = [
    AccumulatedTiebreaker("games", "diff"),     # game differential (library-derived input)
    AccumulatedTiebreaker("runs",  "diff"),     # run differential  (caller input)
    AccumulatedTiebreaker("runs",  "for"),      # runs scored
    HeadToHeadTiebreaker(),                      # relational (cohort pass)
    MiniLeagueTiebreaker(),                      # relational (cohort pass)
]
```

- **Aggregations** (`agg`) the library provides by default: `for` (Σ own), `against` (Σ opp),
  `diff` (`for − against`), `count`, `avg` (`for / count`). The caller picks per input.
- **Multiple inputs** and **explicit order** are just the list — position = priority. The
  existing `WinCountTiebreaker` / `StatTiebreaker` remain valid chain members (the former is
  `Accumulated("wins","for")`; `StatTiebreaker` still reads `Participant.stats` for
  *non-match-derived* values like a seeding rating).
- **Relational tiebreakers** — head-to-head and **mini-league** (rank a tied cohort by a
  sub-table of only their mutual results) need the tied group, so they run as cohort-aware
  reorder passes after scalar ranking (extending today's `_reorder_head_to_head`).
- **App-wide default:** `generate_tournament(..., tiebreakers=[...])` sets a default chain every
  phase inherits unless its `PhaseSpec` overrides it; a single bracket sets it in config as now.

## 7. Re-derivation / correctness

Because totals are accumulated from the games/matches (not stored on `Participant.stats`), every
edit flows through automatically: `report_result`/`report_game` recompute standings on demand,
and the multi-stage `edit_phase_result` / `unwind` gate re-resolves downstream from corrected
results. Differentials, points, and game records all self-correct — the reason this lives in the
engine rather than caller-maintained aggregates.

## 8. Serialization

- `Game` serializes like `Match` (ids preserved as-is); `Match.games` is a list, `Match.stats` /
  `Game.stats` are nested dicts (JSON coerces non-string ids as the model already does).
- `AccumulatedTiebreaker` / `MiniLeagueTiebreaker` / `PointsSystem` get `to_spec`/`from_spec`
  like existing tiebreakers; the tournament default chain serializes in `Tournament.config`.
- `AdvancementType.DRAW` rides the existing enum handling.

## 9. Required engine changes

- **`Game` model + `Match.games` + `Match.stats`**; `report_game` / `unwind_game`; clinch logic
  feeding the existing advancement; `series_score`.
- **`AdvancementType.DRAW` + `report_draw`**; `Standing.draws` / `Standing.points`.
- **`StandingsContext` accumulation** (built-in derived inputs + `stat_for`/`stat_against`/count).
- **`AccumulatedTiebreaker`** (the five aggregations) + **`MiniLeagueTiebreaker`** cohort pass;
  points-aware ranking branch in `tiebreakers/standings.py`.
- **Tournament-level default tiebreaker chain** inherited by phases.

## 10. Open questions

1. **Game-level draws + even BO** — exact rule when an even series ends level in a standings
   phase (match draw) vs. a knockout (force a decider). Drafted in §2; confirm.
2. **Averages / rates** — is `avg` (per-game) enough, or are weighted/percentage aggregations
   wanted (e.g. win %, set ratio)?
3. **Per-game advancement** — v1 only resolves *match* advancement at clinch; no format needs
   mid-series advancement, but flag if that changes.

## 11. Testing plan

- Series: `report_game` clinches at the right count for BO1/3/5/7; `series_score` correct;
  even-BO level series → draw (standings) or error (knockout); `unwind_game` removes one game,
  `unwind_result` clears the series and cascades.
- Accumulation: built-in `games_won/lost` from logs; caller `stat_for/against/count`; `avg`.
- Tiebreakers: explicit order respected; mixed built-in + custom inputs; each aggregation;
  mini-league reorders a constructed tie; chain re-derived after `edit_phase_result`/unwind.
- Draws/points: `report_draw` updates points; rejected for elimination/when disabled.
- Serialization round-trip of a match with a game log and stats, and of a custom chain.
- Back-compat: existing BO1 `report_result` flows unchanged; no `games` ⇒ behaves as today.

## 12. Implementation status

Implemented 2026-06-19 in four slices (each a commit): §1 per-game series
(`Game`/`Match.games`/`report_game`/`unwind_game`/`series_score`); §2–4 accumulation on
`StandingsContext` (`games_won/lost`, `stat_for/against`, `count`); §6 tiebreaker chain
(`AccumulatedTiebreaker` with for/against/diff/count/avg over `wins`/`games`/`draws`/`points`/
caller stats, relational `MiniLeagueTiebreaker`, head-to-head purified to a terminal cohort
reorder); §5 draws + `PointsSystem` (`report_draw`, even-best-of level draws, points-primary
ranking, Swiss pairs by points). Full suite green, mypy strict + ruff clean.

Resolved open questions (§10): even-BO level series settles as a **match draw by games won**
(not aggregate score) where draws are enabled, else errors; `avg` (per-game) is the only rate
aggregation for now; v1 resolves only **match** advancement at clinch (no mid-series advancement).
