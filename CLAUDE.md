# pybracket — agent guide

Storage-agnostic, game-agnostic Python library for running tournaments: bracket generation,
result reporting/unwinding, standings, multi-stage tournaments, and leagues. Pure dataclasses,
no runtime dependencies, immutable-ish (operations return a *new* `Bracket`).

See [README.md](README.md) for user-facing usage and [SPEC.md](SPEC.md) for the full spec.

## Commands

The repo uses a local `.venv` (Python 3.10+). Dev install: `pip install -e ".[dev]"`.

- Tests: `python -m pytest`
- Lint: `python -m ruff check pybracket/ tests/`
- Types: `python -m mypy pybracket/` — `--strict`; `files = ["pybracket"]` in pyproject

All three must stay green. Tests live under `tests/`.

## Architecture

Roughly bottom-up:

- **Models** (`pybracket/models/`) — plain dataclasses: `Bracket`, `Match`, `Game`,
  `Participant`, `Round`, `Standing`, `PointsSystem`, `CrossDivision`, and the multi-stage
  `Tournament`/`Phase`/`SlotRef`/`Qualification`. Enums in `models/enums.py`.
- **Formats** (`pybracket/formats/`) — `generate_*` builders producing a fully-scheduled
  `Bracket`: single/double elim, round-robin, Swiss, gauntlet, and **league**.
- **Advancement** (`pybracket/advancement/engine.py`) — the result engine: `report_result`,
  `report_game` (per-game best-of series), `report_draw`, `unwind_result`/`unwind_game`, bye
  resolution, status recomputation. `placement.py` computes final placements.
- **Tiebreakers** (`pybracket/tiebreakers/`) — `StandingsContext` accumulates records/stats;
  `get_standings` ranks by a caller-owned chain: `AccumulatedTiebreaker` scalars (for/against/
  diff/count/avg over wins/games/draws/points/caller stats) then relational `HeadToHead`/
  `MiniLeague` as terminal cohort reorders.
- **Multi-stage** (`pybracket/tournament.py`) — chains phases of heterogeneous formats with
  `SlotRef`/`Qualification` wiring (season → playoffs, pools → bracket, …).
- **operations.py** — `reseed`, `set_best_of`, `publish_bracket`, and the league `with_*`
  transforms.

Supporting: `seeding/` (snake pools, byes), `naming/` (round names), `utils/` (serialization,
validation, math). `reference-brackets-manager/` is a vendored reference implementation — read
for logic, do not modify.

## Invariants (do not break)

- **Storage-agnostic** — never touches a DB; the caller owns persistence.
- **Game-agnostic: the library names no stat.** Callers own stat names (`"runs"`), aggregations,
  and tiebreaker priority order; the library owns the arithmetic and a few built-in derived
  inputs (wins, games_won/lost, draws, points).
- **Immutable-ish** — `report_*` / `unwind_*` / transforms return a *new* `Bracket`.
- **The ranking engine never reads `Match`/`Game` metadata.** Metadata is caller scratch
  (including the league schedule: `matchweek`/`home_id`/`away_id`/`division`). The blessed
  channels the engine *does* read are `Match.stats` / `Game.stats` and `AdvancementType` — a
  draw is a real result (`AdvancementType.DRAW`), not metadata.
- A league with divisions is **one bracket with division labels** (not separate per-group
  brackets), so cross-division games can span divisions; per-division tables filter that bracket.

## Design docs (all implemented)

Deep specs, kept separate from this file — update their status if behavior changes:

- [SCORING_DESIGN.md](SCORING_DESIGN.md) — per-game series, stat accumulation, the tiebreaker
  chain, draws + points. Library-wide (every format).
- [LEAGUES_DESIGN.md](LEAGUES_DESIGN.md) — `league` format, divisions, cross-division play,
  schedule-in-metadata, `with_*` transforms.
- [MULTISTAGE_DESIGN.md](MULTISTAGE_DESIGN.md) — Tournament/Phase engine, qualification wiring.

## Conventions

- Match the surrounding code; keep mypy `--strict` and ruff clean.
- Branch before committing on `main`; conventional-style commit subjects.
</content>
