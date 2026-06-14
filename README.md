# pybracket

A storage-agnostic, game-agnostic Python library for tournament bracket management.

Supports **single elimination**, **double elimination**, **round robin**, **Swiss**,
**pools**, and **gauntlet** formats.

- **Storage-agnostic.** The library never touches a database. Every operation takes and
  returns plain Python dataclasses; the caller owns persistence.
- **Game-agnostic.** No game-specific logic. Custom stats (run differential, ratings, …)
  flow through `Participant.stats` and a generic `StatTiebreaker`.
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

### Pools → bracket

```python
pools = pb.generate_pools(players, num_pools=2, advancement_count=2)
# Play all pool matches, then snake-seed the survivors into a DRAFT elimination bracket the
# organizer can review (and reorder) before it goes live:
pools = pb.draft_pools_to_bracket(pools)
pools = pb.draft_pools_to_bracket(pools, new_seed_order=[...])  # optional manual reseed
pools = pb.publish_bracket(pools)                               # lock it in for play

# Or do both steps at once:
pools = pb.reseed_pools_to_bracket(pools)
```

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
for development workflow.

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
