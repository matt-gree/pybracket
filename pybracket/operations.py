from __future__ import annotations

import copy
from typing import Any

from .advancement.engine import (
    REAL_RESULTS,
    _apply_format_hooks,
    _draws_allowed,
    settle_initial,
)
from .errors import BracketStateError, ReseedError, ValidationError
from .models.bracket import Bracket
from .models.enums import AdvancementType, BracketState, PairingMethod
from .models.participant import Participant

# A reported result of any kind (incl. a draw) means play has begun.
_PLAYED = REAL_RESULTS | {AdvancementType.DRAW}

__all__ = ["publish_bracket", "reseed", "set_best_of"]


def publish_bracket(bracket: Bracket) -> Bracket:
    """Transition a standalone DRAFT bracket to PUBLISHED, locking it in for play.

    Re-settles the bracket — resolving construction-time byes and initial statuses and
    re-establishing any format-specific frontier (e.g. a gauntlet's opponent-choice round) —
    so play can begin immediately. Use this for a standalone bracket generated in DRAFT; a
    bracket inside a :class:`Tournament` is published via ``publish_phase`` instead.
    """
    if bracket.state is not BracketState.DRAFT:
        raise BracketStateError("Bracket must be in DRAFT state to publish.")
    b = copy.deepcopy(bracket)
    b.state = BracketState.PUBLISHED
    settle_initial(b)
    # Re-establish any format-specific frontier (e.g. a gauntlet's opponent-choice round) that
    # settle_initial does not set up, mirroring generate_* and report_result.
    _apply_format_hooks(b)
    return b


def _has_played(bracket: Bracket) -> bool:
    return any(m.advancement_type in _PLAYED for m in bracket.matches)


def reseed(bracket: Bracket, new_seed_order: list[Any]) -> Bracket:
    """Reorder seeds and regenerate. Valid only before any match has been played."""
    if bracket.state is not BracketState.DRAFT and _has_played(bracket):
        raise BracketStateError(
            "Cannot reseed a published bracket once matches have been played."
        )

    by_id = {p.id: p for p in bracket.participants}
    if set(new_seed_order) != set(by_id):
        raise ReseedError("new_seed_order must be a permutation of the existing participants.")

    reseeded = [
        Participant(id=pid, seed=i + 1, name=by_id[pid].name, stats=dict(by_id[pid].stats))
        for i, pid in enumerate(new_seed_order)
    ]

    from .tiebreakers.standings import deserialize_tiebreakers

    cfg = bracket.config
    fmt = bracket.format

    if fmt == "single_elim":
        from .formats.single_elim import generate_single_elim

        bye_rounds = cfg.get("bye_rounds")
        return generate_single_elim(
            reseeded,
            third_place_match=bool(cfg.get("third_place_match", False)),
            protected_seeds=0 if bye_rounds else int(cfg.get("protected_seeds", 0)),
            bye_rounds={int(k): int(v) for k, v in bye_rounds.items()} if bye_rounds else None,
        )
    if fmt == "double_elim":
        from .formats.double_elim import generate_double_elim

        return generate_double_elim(
            reseeded,
            grand_final_reset=bool(cfg.get("grand_final_reset", True)),
            protected_seeds=int(cfg.get("protected_seeds", 0)),
        )
    if fmt == "round_robin":
        from .formats.round_robin import generate_round_robin

        return generate_round_robin(
            reseeded, tiebreakers=deserialize_tiebreakers(cfg.get("tiebreakers"), reseeded)
        )
    if fmt == "league":
        from .formats.league import generate_league

        return generate_league(
            reseeded,
            best_of=int(cfg.get("best_of", 1)),
            points=cfg.get("points_system"),
            tiebreakers=deserialize_tiebreakers(cfg.get("tiebreakers"), reseeded),
        )
    if fmt == "swiss":
        from .formats.swiss import generate_swiss

        method = cfg.get("pairing_method", PairingMethod.DUTCH)
        if isinstance(method, str):
            method = PairingMethod(method)
        return generate_swiss(
            reseeded,
            rounds=int(cfg["rounds"]) if "rounds" in cfg else None,
            pairing_method=method,
            tiebreakers=deserialize_tiebreakers(cfg.get("tiebreakers"), reseeded),
            allow_bye=bool(cfg.get("allow_bye", True)),
        )
    if fmt == "gauntlet":
        from .formats.gauntlet import generate_gauntlet

        return generate_gauntlet(
            reseeded,
            style=cfg.get("style", "single"),
            opponent_choice=bool(cfg.get("opponent_choice", False)),
            choice_scope=cfg.get("choice_scope", "round"),
        )
    raise ReseedError(f"Reseeding is not supported for format {fmt!r}.")


def set_best_of(
    bracket: Bracket,
    best_of: int,
    round_overrides: dict[int, int] | None = None,
) -> Bracket:
    """Set best-of globally and/or per round. Only before the affected rounds begin.

    ``best_of`` must be positive. An even best_of (a series that can end level) is allowed only
    where draws are enabled, since a level even series settles as a match draw.
    """
    for value in [best_of, *(round_overrides or {}).values()]:
        if value < 1:
            raise ValidationError("best_of must be a positive integer.")
        if value % 2 == 0 and not _draws_allowed(bracket):
            raise ValidationError(
                "An even best_of is only allowed when draws are enabled (a level series draws)."
            )

    started: set[int] = {
        m.round_number for m in bracket.matches if m.advancement_type in _PLAYED
    }

    if bracket.state is not BracketState.DRAFT:
        if round_overrides is None and started:
            raise BracketStateError(
                "Cannot change best-of globally after matches have been played."
            )
        if round_overrides is not None:
            conflict = started & set(round_overrides)
            if conflict:
                raise BracketStateError(
                    f"Rounds {sorted(conflict)} have already begun; cannot change best-of."
                )

    b = copy.deepcopy(bracket)
    overrides = round_overrides or {}
    for m in b.matches:
        m.best_of = overrides.get(m.round_number, best_of)
    for r in b.rounds:
        if r.number in overrides:
            r.best_of = overrides[r.number]
    return b
