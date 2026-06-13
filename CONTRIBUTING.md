# Contributing to pybracket

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Workflow

Tests are written *alongside* implementation, never after. Every format, every edge case,
and every pairing rule has a corresponding test.

```bash
pytest                 # run the test suite
mypy pybracket         # strict type checking
ruff check pybracket   # lint
```

All four must pass before a change is considered done.

## Conventions

- **Python 3.10+.** Use `match` statements and `X | Y` union types.
- `from __future__ import annotations` at the top of every module.
- `__all__` defined in every `__init__.py`; only export intentionally public names.
- No global mutable state. Functions are pure: input → output.
- One-line docstrings on public functions. Type hints are the documentation for parameters.
- Comments explain *why* (a specific FIDE rule, a non-obvious algorithm step, a ported
  test source), never *what*.
- Tests ported from brackets-manager.js are commented with
  `# Ported from brackets-manager.js test/<file>.spec.js`.
- Tests derived from the FIDE handbook cite the source, e.g.
  `# Source: FIDE Handbook C.04.3, Example N`.

## Errors

Raise the specific exceptions from `pybracket.errors`:

| Exception | Raised when |
|---|---|
| `BracketStateError` | operation not valid in the current bracket state |
| `MatchNotFoundError` | `match_id` not in the bracket |
| `ParticipantNotFoundError` | `participant_id` not in the match |
| `InvalidResultError` | `winner_id` is not a participant in the match |
| `ReseedError` | reseeding conflicts with completed matches |
| `SwissRoundIncompleteError` | `advance_swiss_round()` called before the round is done |

## Attribution

When porting logic from brackets-manager.js, do not copy TypeScript verbatim — port the
logic and translate tests to pytest. Keep the dual MIT attribution in `LICENSE` intact.
