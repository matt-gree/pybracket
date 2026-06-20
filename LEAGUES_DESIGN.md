# Leagues — design

Status: **proposal** (no code yet). Target: league / regular-season play as a first-class
phase — round-robin at heart, but with **divisions**, **cross-division play**, an **optional
points system with draws**, **home/away (double) scheduling**, **best-of per match**, and a
TO-editable **schedule** — all expressed as composable transformations over a base league, and
plugging into the existing multi-stage `Tournament` (so a regular season feeds a playoff
bracket for free).

This builds on [MULTISTAGE_DESIGN.md](MULTISTAGE_DESIGN.md): a league is a **Phase format**, so
a single-phase `Tournament` *is* a standalone league, and `league → playoffs` is just a second
phase with a `Qualification`.

## 1. Motivation

Today round-robin is a single cycle scheduled by the circle method; "pools" is a grouped
round-robin phase. Neither models a real league season: no return fixtures (home/away), no
cross-division games, no points/draws, no editable matchweek schedule. Leagues are the most
common "regular season" shape and the natural front half of `season → playoffs`.

The TO's mental model (from design Q&A): *set up divisions, then apply transformations* — make
it home-and-away, or best-of-3, decide how many cross-division games and how opponents are
chosen, and adjust the schedule (what plays when). The library should offer **sensible
auto-generated defaults plus a few named strategies**, and let the TO edit from there.

## 2. Decisions (from design Q&A)

1. **Scoring is win/loss by default, with an optional points layer.** No points system →
   rank by record (today's behaviour). Attach a `PointsSystem` → standings rank by points and
   **draws become representable**. Flexibility without forcing soccer semantics on BO-style
   leagues.
2. **A league is a Phase format.** A one-phase `Tournament` is a standalone league; multi-phase
   gives `season → playoffs`. No separate top-level league type.
3. **Cross-division play is auto-generated from a game count, with a pairing strategy** the TO
   picks: `balanced` (by seed), `random`, or `top_seed_favored`. (Plus "none" = isolated
   divisions = today's pools.)
4. **The schedule lives in match metadata**, not a heavy new object: matchweek, home/away,
   date, venue, etc. The generator *writes* these; the TO edits them. The ranking engine never
   reads metadata (preserving the existing invariant) — see §6.
5. **`league` is its own format** (not sugar over `round_robin`). Confirmed: the config surface
   (divisions + cross-division + double + points) and the schedule don't fit the plain RR
   primitive, which stays simple.
6. **Tiebreakers are two-track** (the run-differential question). Match-derived aggregates go
   through a new first-class per-match *score* the library sums and re-derives; opaque/external
   stats keep using `Participant.stats` + `StatTiebreaker`. See §5.

## 3. Conceptual model

A league is a generalized round-robin phase:

```
Phase(format="league", groups=D, config={
    "double": False,                 # False = single RR, True = home/away double RR
    "best_of": 1,                    # per-match games (BO1/BO3/…); TO can override per round
    "points": None | PointsSystem,   # None = win/loss record; else points + draws
    "cross_division": CrossDivision | None,   # inter-division games (only meaningful if D>1)
    "schedule": "circle" | "manual", # how matchweeks are generated
})
```

- `groups=D` are the **divisions** (reuses the grouping mechanism: snake assignment, per-group
  standings, overall standings — all already in `phase_results`).
- With `D==1` it is a plain league table; with `D>1` it is divisions plus optional
  cross-division games.
- Output is **standings** (per division and overall), so a downstream `Qualification`
  (`top_of_each_group("season", 1)` for division winners, `top("season", 6)` for wildcards)
  feeds a playoff bracket exactly like Swiss→top-cut today.

### Why a new `league` format vs. extending `round_robin`

`round_robin` stays the simple primitive (one cycle, no points, no divisions-with-crossplay).
`league` is the composite that adds divisions+crossplay+double+points. They share the circle-
method scheduler and the standings engine; `league` is "round-robin with a richer config and a
schedule". (Alternatively `league` could be sugar that lowers to `round_robin`+config — decided
in §13.)

## 4. Match-model changes

### 4a. Draws

Draws are a real result the engine must score (not metadata). Minimal addition:

- `AdvancementType.DRAW` — a completed match with `winner_id = loser_id = None` and
  `advancement_type = DRAW`.
- `report_draw(bracket, match_id, metadata=None) -> Bracket` — the draw analogue of
  `report_result`. **Valid only for standings-based formats** (`round_robin`, `league`, Swiss
  if enabled) and only when the phase's `PointsSystem` allows draws; raises for elimination
  (a knockout match must produce a winner) and when draws are disabled.
- `unwind_result` already keys on "has a real result"; it extends to clear a `DRAW`.

`Standing` gains `draws: int` and `points: float`. `Standing.advancement_type_counts` already
exists, so draw counts ride along naturally.

BO-N interaction: an odd `best_of` cannot draw; an even `best_of` (e.g. a two-game series) can
end level — permitted only when the points system allows draws.

### 4b. Optional per-match score (for match-derived tiebreakers)

Sport tiebreakers like **run differential** or **goal difference** accumulate from match
scores. Rather than make the caller maintain a running aggregate on `Participant.stats` (which
the edit/unwind gate can't auto-correct), the engine gets a *first-class, optional* per-match
score it can aggregate and re-derive:

- `Match.score: tuple[float, float] | None = None` — participant1's tally vs participant2's
  tally for the match. **Not metadata** — a blessed channel the ranking engine may read.
- `report_result(bracket, match_id, winner_id, *, score=(7, 3), …)` — optional `score`.
- `StandingsContext` aggregates `points_for[pid]` / `points_against[pid]` from `score` across a
  participant's matches.

The library stays game-agnostic: it never knows "runs" or "goals", only "each match has two
numeric tallies". The caller maps their domain onto the pair (baseball `(runs, runs)`; a BO3
league `(maps_won, maps_lost)`). Because differentials are re-derived from the matches, an
`edit_phase_result` / `unwind` corrects them automatically — the whole point of doing it here
rather than on `Participant.stats`.

## 5. Points and standings

```python
@dataclass(frozen=True)
class PointsSystem:
    win: float = 3
    draw: float = 1
    loss: float = 0
    draws_allowed: bool = True
    # optional regulation/overtime split later (e.g. hockey OTW/OTL); out of scope for v1
```

- **No `PointsSystem`** → `get_standings` ranks by record (wins, then tiebreakers) — unchanged.
- **With `PointsSystem`** → standings rank by `points` first, then the configured tiebreakers.
  Points-aware ranking is a new branch in `tiebreakers/standings.py`.
League tiebreakers are **two-track**, which answers "how do sport tiebreakers like run
differential fit a game-agnostic library?":

- **Match-derived aggregates** — `DifferentialTiebreaker` (`Σpoints_for − Σpoints_against`) and
  `PointsForTiebreaker` (`Σpoints_for`) read the §4b per-match `score` from `StandingsContext`.
  The library does the arithmetic and re-derives on every edit/unwind; the caller only chooses
  what the two tallies *mean*. This is the recommended home for run/goal differential, points
  scored, map differential, etc.
- **Opaque / external stats** — `StatTiebreaker(stat_key=…)` keeps reading `Participant.stats`
  for values the library can't derive from matches (a pre-season rating, a manual override, a
  coin flip). The caller owns these because they aren't match-derived.
- Plus the existing outcome-derived tiebreakers (head-to-head, Buchholz-style strength of
  schedule). A "mini-league among tied teams" tiebreaker (results restricted to the tied set)
  is a candidate addition (§13).

## 6. Scheduling (matchweeks via metadata)

The schedule is the existing `Round` list (one **matchweek** per round) plus per-match
metadata. The generator writes, the TO edits; the **ranking engine never reads metadata**.

Per-match metadata keys the generator writes:

```
{ "matchweek": 3, "home_id": 12, "away_id": 7, "date": None, "venue": None }
```

- **Single RR (`double=False`):** circle method as today; each pairing once. `home_id`/`away_id`
  alternate to balance home/away across the season.
- **Home/away (`double=True`):** every pairing twice with venues swapped; matchweeks are
  mirrored (week *k* and week *k+R*), the standard double-round-robin construction. Balanced so
  no team plays too many consecutive home/away (best-effort; §13 for hard constraints).
- **Odd team count:** a bye each matchweek (one team rests), recorded as a `BYE`/`NOT_NEEDED`
  match or a `metadata["bye_id"]` on the round — matching how round-robin handles odd fields.
- **Editing:** the TO reorders matchweeks or swaps a match's `matchweek`/`home_id`/`venue` in
  metadata; nothing in standings depends on it, so edits never invalidate results.

A `league_schedule(bracket) -> list[Matchweek]` view assembles the rounds+metadata into a
convenient read model (matchweek → list of fixtures) for UIs, without storing a second copy.

## 7. Cross-division play

Only relevant when `groups (D) > 1`. The TO supplies how many inter-division games each team
plays and a strategy for choosing opponents:

```python
@dataclass(frozen=True)
class CrossDivision:
    games_per_team: int                 # inter-division games each team plays
    pairing: str = "balanced"           # 'balanced' | 'random' | 'top_seed_favored' | 'round_robin'
    repeat_home_away: bool = False      # if True, each cross pairing is played twice (H/A)
```

`pairing` strategies (how to choose each team's cross-division opponents when you can't play
everyone):

- **`balanced`** — opponents of *matching rank* across divisions (a team's nth seed plays other
  divisions' nth seeds), so strength of schedule is symmetric. The default.
- **`top_seed_favored`** — stronger teams get a marginally easier cross slate (or top seeds are
  steered apart), a deliberate competitive-balance lever.
- **`random`** — uniformly random legal opponents (seeded RNG for reproducibility).
- **`round_robin`** — if `games_per_team` allows, play *all* other-division teams (full
  interleague); the others are partial rotations.

Intra-division games are a full single/double RR within each division; cross games are layered
on top into additional matchweeks. Total games per team =
`(division size − 1) × (1 or 2) + games_per_team × (1 or 2)`.

## 8. Transformations (the composable API)

The TO's "set up divisions, then apply home/away or BO3" maps to transforms that each return a
new bracket/phase (immutable-ish, like the rest of the library):

```python
league = generate_league(teams, divisions=4)          # base: 4-division single RR, win/loss
league = with_home_away(league)                        # -> double round-robin, venues assigned
league = with_best_of(league, 3)                       # BO3 every match (per-round override ok)
league = with_points(league, PointsSystem())           # W/D/L points + draws
league = with_cross_division(league, CrossDivision(games_per_team=2, pairing="balanced"))
```

Equivalently, all of it can be passed to `generate_league(...)`/`PhaseSpec(... config=…)` up
front; the `with_*` transforms are sugar that rebuild the schedule with the new option. Because
a league is a Phase, the same options are just `PhaseSpec("season", "league", groups=4,
config={…})` inside a `Tournament`.

Transforms operate **before play starts** (DRAFT/PUBLISHED with no results); applying one after
results exist raises, mirroring `reseed`'s state rules. (`set_best_of` already exists and is the
template for `with_best_of`.)

## 9. Suggested format presets

Thin recipes (frontend/`examples`, returning a plain league/Tournament — not blessed types,
per the pools→bracket decision):

| Preset | Shape |
| ------ | ----- |
| Soccer league | 1 division, `double=True`, `PointsSystem(3,1,0)`, BO1 |
| Group stage → knockout | `league` phase (D groups, single RR) → `single_elim`/`double_elim` via `top_of_each_group` |
| Conference season → playoffs | `league` D=2 with `CrossDivision`, then a seeded bracket pulling division winners + wildcards |
| Esports BO3 league | 1 division, single RR, `with_best_of(3)`, win/loss |

## 10. Integration with multi-stage

Nothing new: `league` produces standings, so it slots into a `Tournament` like any standings
format. `phase_results(t, "season", group=d)` gives a division table; `group=None` the overall
table; a downstream `Qualification` selects qualifiers. The §11 edit/unwind gate and the
draft/publish lifecycle apply unchanged.

## 11. Serialization

- `PointsSystem` / `CrossDivision` are flat dataclasses stored in the phase/bracket `config`
  (extend `_config_to_dict`/`_from_dict`, like `PairingMethod` today).
- Schedule lives in `Round`s + match `metadata`, both already serialized.
- `AdvancementType.DRAW` round-trips through the existing enum handling.
- `Match.score` serializes as a 2-element list or `null`.

## 12. Required engine changes

- **`AdvancementType.DRAW` + `report_draw` + `unwind` of a draw** (advancement engine).
- **Optional `Match.score`** (§4b) + `report_result(..., score=)`; `StandingsContext` aggregates
  `points_for`/`points_against`; new `DifferentialTiebreaker` / `PointsForTiebreaker`.
- **`Standing.draws` / `Standing.points`; points-aware ranking** in `tiebreakers/standings.py`,
  gated on a configured `PointsSystem`.
- **`league` format + `generate_league` + schedule generator** (single/double RR, byes,
  home/away balancing) reusing `circle_method_rounds`.
- **Cross-division scheduler** (the four `pairing` strategies).
- **`league_schedule` view** and the `with_*` transforms.
- `get_placements` / `phase_results` already dispatch standings formats — add `"league"` to the
  standings set.

## 13. Open questions

Resolved: **`league` is its own format** (not RR sugar). **Home/away balancing** is in (v1
best-effort: alternate venues, mirror the two halves; no hard constraint solver). **Run-style
tiebreakers** use the §4b per-match `score` + a generic `DifferentialTiebreaker`.

Still open:

1. **Mini-league tiebreaker** (rank tied teams by results among themselves only) — add to the
   tiebreaker chain, or leave to the differential/stat tracks?
2. **Home/away hard constraints** (no 3 consecutive home games, derby spacing) — a later
   constraint solver, or is best-effort balancing enough indefinitely?
3. **OT/shootout points** (hockey-style regulation vs OT win) — extend `PointsSystem`, or out
   of scope?
4. **Two-leg aggregate ties** (sum of home+away scores to decide a single winner) — this is a
   *bracket* concept, not a league; track separately if wanted.

## 14. Testing plan

- Single & double RR schedules: every pairing appears the right number of times; home/away
  balance; correct matchweek count; odd-field byes.
- Cross-division: each strategy produces the right game counts and legal (inter-division)
  opponents; `balanced` is rank-symmetric; `random` is reproducible under a fixed seed.
- Draws: `report_draw` updates points/standings; rejected for elimination and when disabled;
  unwind of a draw restores standings.
- Score / differential: `report_result(score=…)` feeds `points_for`/`points_against`;
  `DifferentialTiebreaker` orders correctly and is **re-derived after an `edit_phase_result` /
  unwind** (the reason it lives in the engine, not `Participant.stats`).
- Points standings: ordering by points then tiebreakers; win/loss mode unchanged when no
  `PointsSystem`.
- Transforms: `with_home_away` / `with_best_of` / `with_points` / `with_cross_division` rebuild
  correctly and raise once results exist.
- Integration: `league → playoffs` end-to-end; division winners + wildcards seeded into a
  bracket; serialization round-trip of a configured league.
