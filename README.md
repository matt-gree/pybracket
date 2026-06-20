# pybracket

A storage-agnostic, game-agnostic Python library for tournament bracket management.

Supports **single elimination**, **double elimination**, **round robin**, **Swiss**,
**gauntlet**, and **league** formats; chains them into **multi-stage tournaments** (pools →
bracket, season → playoffs); and layers in a library-wide scoring system — **best-of series**,
**points & draws**, and a **caller-owned tiebreaker chain**.

- **Storage-agnostic.** The library never touches a database. Every operation takes and
  returns plain Python dataclasses; the caller owns persistence.
- **Game-agnostic — the library names no stat.** You supply stat names (per game or match),
  choose aggregations (for / against / diff / count / avg) and tiebreaker priority order; the
  library does the arithmetic. Static ratings still flow through `Participant.stats`.
- **Immutable-ish.** `report_result()`, `unwind_result()`, and the round-advancing helpers
  return a *new* `Bracket` rather than mutating in place, so callers can diff before/after.
- **No runtime dependencies.** The core has zero third-party runtime dependencies.

## Installation

```bash
pip install -e ".[dev]"   # editable install with test/lint tooling
```

Requires Python 3.10+.

## Quickstart

```python
import pybracket as pb

players = [
    pb.Participant(id=i, seed=i, name=f"Player {i}")
    for i in range(1, 9)
]

bracket = pb.generate_single_elim(players, third_place_match=True)

# Play the tournament: report results until complete.
while not pb.is_complete(bracket):
    for match in pb.get_ready_matches(bracket):
        # The caller decides who wins (lower seed wins, here).
        p1 = pb.get_participant(bracket, match.participant1_id)
        p2 = pb.get_participant(bracket, match.participant2_id)
        winner = min((p1, p2), key=lambda p: p.seed)
        bracket = pb.report_result(bracket, match.id, winner.id)

champion = pb.get_winner(bracket)
print(f"Winner: {champion.name}")

for placement in pb.get_placements(bracket):
    print(placement.position_label, placement.participant_id)
```

### Swiss

```python
bracket = pb.generate_swiss(players, pairing_method=pb.PairingMethod.DUTCH)
# Play round 1...
# then generate the next round's pairings:
bracket = pb.advance_swiss_round(bracket)
```

### Best-of series, points & tiebreakers

Track each game of a best-of-N match (not just the series winner), award points with draws,
and rank by a tiebreaker chain you control. This layer is library-wide — any format can use it.

```python
# Report game-by-game; the match resolves at the clinch (best_of // 2 + 1) and advances.
bracket = pb.set_best_of(bracket, 3)
bracket = pb.report_game(bracket, match_id, winner_id, stats={"runs": (7, 3)})
pb.get_match(bracket, match_id).series_score   # -> (games_p1, games_p2)

# Standings formats can carry points + draws:
rr = pb.generate_round_robin(players, tiebreakers=[
    pb.AccumulatedTiebreaker("runs", "diff"),   # run differential, then ...
    pb.HeadToHeadTiebreaker(),                   # relational: breaks remaining ties
])
rr.config["points_system"] = pb.PointsSystem(win=3, draw=1, loss=0)
rr = pb.report_draw(rr, match_id)                # a no-winner result (standings only)

# Ranked by points (auto-primary when a PointsSystem is set), then your chain.
standings = pb.get_standings(rr)
```

See [SCORING_DESIGN.md](SCORING_DESIGN.md).

### Leagues (regular-season play)

A `league` is a round-robin season with a schedule, optional divisions, cross-division play,
and home/away double rounds — built up with composable transforms (valid before play starts).

```python
league = pb.generate_league(teams, divisions=2)              # 2-division single round-robin
league = pb.with_home_away(league)                            # home/away double round-robin
league = pb.with_points(league, pb.PointsSystem(3, 1, 0))
league = pb.with_cross_division(
    league, pb.CrossDivision(games_per_team=2, pairing="balanced"))

pb.division_standings(league, 0)   # one division's table; pb.get_standings(league) -> overall
pb.league_schedule(league)         # matchweeks -> fixtures (home/away/division) for UIs
```

The schedule lives in match metadata (matchweek, home/away, venue) the TO can edit freely. A
league is also a `Phase` format, so `season → playoffs` is just a `Tournament` whose second
phase pulls qualifiers via a `Qualification`. See [LEAGUES_DESIGN.md](LEAGUES_DESIGN.md).

### Multi-stage tournaments (pools → bracket and beyond)

Chain phases of any formats under one `Tournament`. "Pools" is just a grouped round-robin
phase (`groups=N`); the bracket is the next phase, pulling qualifiers via a `Qualification`.

```python
t = pb.generate_tournament(players, phases=[
    pb.PhaseSpec("pools", "round_robin", groups=2),           # phase 0, built live
    pb.PhaseSpec("cut", "double_elim",
                 entrants=pb.Qualification(
                     sources=pb.top_of_each_group("pools", 2),  # top 2 of each pool
                     seeding="snake")),
])

# Play each pool with the normal report_result, putting the result back on the phase:
for i, bracket in enumerate(t.phases[0].brackets):
    t.phases[0].brackets[i] = play(bracket)

# Snake-seed the survivors into a DRAFT bracket the organizer can review (and reorder),
# then lock it in for play:
t = pb.draft_phase(t, "cut")
t = pb.draft_phase(t, "cut", new_seed_order=[...])  # optional manual reseed
t = pb.publish_phase(t, "cut")
t = pb.advance_phase(t, "cut")                       # or do draft + publish in one step
```

This generalizes to any chain — Swiss → top-cut, pools → pools → bracket, or the high/low
merge where one pool seeds everyone and another cuts to its top-N (`pb.all_of("pools#0") +
pb.top("pools#1", 4)`). See `MULTISTAGE_DESIGN.md`.

### Multi-round byes (single elimination)

```python
# Seeds 1-2 enter in round 3, seeds 3-4 enter in round 2, seeds 5-8 play round 1.
bracket = pb.generate_single_elim(players, bye_rounds={1: 2, 2: 2, 3: 1, 4: 1})

# Specify only the byes you care about — the engine fills in the rest. For a 16-team field,
# "the top four get a double bye" auto-completes with single byes for seeds 5-8.
bracket = pb.generate_single_elim(players_16, bye_rounds={1: 2, 2: 2, 3: 2, 4: 2})
bracket.config["bye_rounds_added"]  # -> {5: 1, 6: 1, 7: 1, 8: 1}

# Discover the bye configurations a field size supports (Big-12 style, etc.).
for option in pb.allowable_bye_options(14):
    print(option.rounds, option.label())  # e.g. "4×double, 6×single, 4 play in"
```

### Correcting a result

```python
bracket, signals = pb.unwind_result(bracket, match_id)
for signal in signals:
    # signal.metadata carries whatever you attached (game ids, etc.)
    scrub_game_record(signal.metadata)
```

### Serialization

```python
data = pb.bracket_to_dict(bracket)
same = pb.bracket_from_dict(data)        # round-trips with no data loss
text = pb.bracket_to_json(bracket)
same = pb.bracket_from_json(text)
```

## Design

See [SPEC.md](SPEC.md) for the full specification and [CONTRIBUTING.md](CONTRIBUTING.md)
for development workflow. Feature design docs:

- [SCORING_DESIGN.md](SCORING_DESIGN.md) — best-of series, stat accumulation, the tiebreaker
  chain, draws & points.
- [LEAGUES_DESIGN.md](LEAGUES_DESIGN.md) — the `league` format, divisions, cross-division play,
  schedule, and transforms.
- [MULTISTAGE_DESIGN.md](MULTISTAGE_DESIGN.md) — the Tournament/Phase engine and qualification
  wiring.

## Acknowledgements

pybracket is informed by and partially derived from
[brackets-manager.js](https://github.com/Drarig29/brackets-manager.js) by
[Corentin Girard (Drarig29)](https://github.com/Drarig29), released under the MIT License.
The double-elimination loser-drop placement and seed-ordering methods are ports of its
algorithms.

The Swiss pairing implementation follows the
[FIDE (Dutch) System, Handbook C.04.3](https://handbook.fide.com/chapter/C0403202602)
and the [FIDE General Handling Rules for Swiss Tournaments](https://handbook.fide.com/chapter/GeneralHandlingRulesForSwissTournaments202507).

Seeding theory draws on:

- *Optimal Seedings in Elimination Tournaments* — Moldovanu, Sela, et al.
- *Optimal Seedings Revisited* (Springer)
- *A Theory of Knockout Tournament Seedings* (Heidelberg)
- *Who Can Win a Single-Elimination Tournament?* (arXiv:1511.08416)
- *Competitive Intensity and Quality Maximizing Seedings* (Springer)
- *Tournament Design: A Review from an OR Perspective* (arXiv:2404.05034)

## License

MIT. See [LICENSE](LICENSE) — it carries both the pybracket and brackets-manager.js
copyright notices.
