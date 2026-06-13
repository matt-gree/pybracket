from __future__ import annotations

import copy
from typing import Any

from .advancement.engine import REAL_RESULTS
from .errors import BracketStateError, ReseedError, ValidationError
from .models.bracket import Bracket
from .models.enums import BracketState, PairingMethod
from .models.participant import Participant

__all__ = ["reseed", "set_best_of"]


def _has_played(bracket: Bracket) -> bool:
    return any(m.advancement_type in REAL_RESULTS for m in bracket.matches)


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

        return generate_single_elim(
            reseeded,
            third_place_match=bool(cfg.get("third_place_match", False)),
            protected_seeds=int(cfg.get("protected_seeds", 0)),
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
    """Set best-of globally and/or per round. Only before the affected rounds begin."""
    if best_of < 1 or best_of % 2 == 0:
        raise ValidationError("best_of must be a positive odd number.")

    started: set[int] = {
        m.round_number for m in bracket.matches if m.advancement_type in REAL_RESULTS
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
