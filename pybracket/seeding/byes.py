"""Multi-round byes for single elimination, modelled as a Kraft tiling.

A seed that skips ``b`` rounds (``b`` byes) enters at round ``b + 1`` and conceptually occupies
a ``2**b`` block of a perfect ``2**R``-leaf bracket. A bye configuration therefore produces a
valid bracket exactly when the blocks tile that perfect tree::

    sum(2**byes[seed] for seed in field) == 2**R

This module owns three things built on that identity:

* :func:`complete_bye_rounds` -- take the byes a TO actually cares about (e.g. "the top four
  seeds get double byes") and fill in the minimal extra byes needed to reach a clean bracket,
  reporting what was added.
* :func:`allowable_bye_options` -- enumerate the valid bye profiles for a field size, so the
  options can be surfaced to the TO instead of guessed at.
* :func:`build_bye_plan` -- turn a completed (tiling) byes map into an abstract bracket tree in
  standard seed order, so the emitted matches respect seeding *and* render cleanly (sibling
  matches stay adjacent, seeds 1 and 2 land in opposite halves).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import ValidationError
from ..utils.math import is_power_of_2, log2_int

__all__ = [
    "ByeCompletion",
    "ByeProfile",
    "complete_bye_rounds",
    "allowable_bye_options",
    "build_bye_plan",
    "ByeNode",
    "SeedLeaf",
    "MatchNode",
]


# --------------------------------------------------------------------------------------
# Abstract bracket plan (pure; the format layer turns this into real Match objects)
# --------------------------------------------------------------------------------------

# A leaf is a seed entering directly (it byes through every round below this point).
SeedLeaf = tuple[str, int]  # ("seed", seed_number)
# A match at ``round_number`` fed by two child nodes.
MatchNode = tuple[str, int, "ByeNode", "ByeNode"]  # ("match", round_number, left, right)
ByeNode = SeedLeaf | MatchNode


# --------------------------------------------------------------------------------------
# Completion report
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ByeCompletion:
    """The result of completing a partial bye request into a tiling configuration."""

    completed: dict[int, int]  # full seed -> byes map that tiles a 2**rounds bracket
    requested: dict[int, int]  # the byes the caller asked for (unspecified seeds = 0)
    added: dict[int, int]  # seed -> byes the engine added beyond the request (positive only)
    rounds: int  # total rounds in the resulting bracket (final is round ``rounds``)

    @property
    def changed(self) -> bool:
        """True when the engine had to add byes to make the request work."""
        return bool(self.added)


@dataclass(frozen=True)
class ByeProfile:
    """One valid bye configuration for a field size, summarised by counts per bye level."""

    rounds: int
    counts: dict[int, int] = field(default_factory=dict)  # bye level -> number of seeds

    @property
    def doubles(self) -> int:
        return self.counts.get(2, 0)

    @property
    def singles(self) -> int:
        return self.counts.get(1, 0)

    def to_bye_rounds(self) -> dict[int, int]:
        """Expand the level counts into a seed -> byes map (top seeds get the most byes)."""
        out: dict[int, int] = {}
        seed = 1
        for level in sorted(self.counts, reverse=True):
            for _ in range(self.counts[level]):
                out[seed] = level
                seed += 1
        return out

    def label(self) -> str:
        parts: list[str] = []
        for level in sorted((b for b in self.counts if b >= 1), reverse=True):
            word = {1: "single", 2: "double", 3: "triple"}.get(level, f"{level}-round")
            parts.append(f"{self.counts[level]}×{word}")
        base = self.counts.get(0, 0)
        parts.append(f"{base} play in" if base else "no play-in")
        return ", ".join(parts)


# --------------------------------------------------------------------------------------
# Validation of a raw request
# --------------------------------------------------------------------------------------


def _validate_requested(n: int, requested: dict[int, int]) -> dict[int, int]:
    """Validate the raw seed -> byes request and return a full per-seed map (0 for unspecified)."""
    for seed, count in requested.items():
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValidationError(
                f"bye_rounds value for seed {seed} must be an integer, got {count!r}."
            )
        if count < 0:
            raise ValidationError(
                f"bye_rounds value for seed {seed} must be non-negative, got {count}."
            )
        if not (1 <= seed <= n):
            raise ValidationError(
                f"bye_rounds references seed {seed}, which has no matching participant."
            )

    byes = {s: int(requested.get(s, 0)) for s in range(1, n + 1)}

    # Byes must be non-increasing by seed: a worse seed can never get more byes than a better
    # one, otherwise the top seeds are no longer the ones being protected.
    previous: int | None = None
    for s in range(1, n + 1):
        if previous is not None and byes[s] > previous:
            raise ValidationError(
                f"bye_rounds must be non-increasing by seed: seed {s} is given more byes "
                f"({byes[s]}) than a better-ranked seed ({previous})."
            )
        previous = byes[s]
    return byes


# --------------------------------------------------------------------------------------
# Completion: fill the minimal extra byes to reach a tiling bracket
# --------------------------------------------------------------------------------------


def _ceil_log2(n: int) -> int:
    return 0 if n <= 1 else (n - 1).bit_length()


def _fill_deficit(byes: dict[int, int], n: int, deficit: int, rounds: int) -> None:
    """Raise byes in place to add exactly ``deficit`` units of bracket capacity.

    Each promotion of a seed from ``b`` to ``b + 1`` byes adds ``2**b`` capacity. We prefer to
    spread single byes across the strongest seeds that don't have one yet (the Big-12 shape --
    top seeds double-byed, the next tier single-byed) by always promoting the strongest seed at
    the current lowest bye level that still has monotonic room.
    """
    while deficit > 0:
        candidates = [
            s
            for s in range(1, n + 1)
            if byes[s] <= rounds - 2  # may rise to at most rounds - 1 (enter the final)
            and (s == 1 or byes[s - 1] > byes[s])  # keep byes non-increasing
            and (1 << byes[s]) <= deficit  # don't overshoot
        ]
        if not candidates:
            raise ValidationError(
                "Could not auto-complete the requested byes into a valid bracket. "
                "Use allowable_bye_options() to see the configurations this field supports."
            )
        seed = min(candidates, key=lambda s: (byes[s], s))
        deficit -= 1 << byes[seed]
        byes[seed] += 1


def complete_bye_rounds(n: int, requested: dict[int, int]) -> ByeCompletion:
    """Complete a partial bye request into a tiling configuration, reporting what was added.

    ``requested`` maps a seed number to the byes the TO insists on; unspecified seeds default
    to zero and may be given byes by the engine. The result tiles a perfect ``2**rounds``
    bracket, stays non-increasing by seed, and never reduces a requested seed below its
    request. A universal bye (every seed skips round 1) is normalised away.
    """
    if n < 1:
        raise ValidationError("Cannot build byes for an empty field.")
    byes = _validate_requested(n, requested)

    kraft = sum(1 << byes[s] for s in range(1, n + 1))
    rounds = max(_ceil_log2(kraft), _ceil_log2(n))
    # The top seed must still fit below the final: byes <= rounds - 1.
    rounds = max(rounds, max(byes.values()) + 1) if n > 1 else max(rounds, 0)

    _fill_deficit(byes, n, (1 << rounds) - kraft, rounds)

    # A bye every seed shares isn't a bye -- it just means round 1 has nobody in it. That only
    # happens when the request asks for more byes than the field can carry (e.g. seed 1 byed
    # past a gauntlet, or byes on a field that is already a clean power of two).
    if n > 1 and min(byes.values()) > 0:
        raise ValidationError(
            "The requested byes cannot be honoured by a field of "
            f"{n}: they would leave round 1 empty. Use allowable_bye_options() to see the "
            "configurations this field supports."
        )

    requested_full = {s: int(requested.get(s, 0)) for s in range(1, n + 1)}
    added = {s: byes[s] - requested_full[s] for s in range(1, n + 1) if byes[s] > requested_full[s]}
    return ByeCompletion(completed=byes, requested=dict(requested), added=added, rounds=rounds)


# --------------------------------------------------------------------------------------
# Enumeration of allowable bye profiles for a field size
# --------------------------------------------------------------------------------------


def allowable_bye_options(
    n: int, *, extra_rounds: int = 1, max_bye_level: int = 3
) -> list[ByeProfile]:
    """Enumerate the bye configurations a field of ``n`` players can support.

    Returns one :class:`ByeProfile` per valid set of bye-level counts, for bracket sizes from
    the smallest that fits ``n`` up to ``extra_rounds`` rounds larger. Bye levels are capped at
    ``max_bye_level`` to keep the list focused on the configurations a TO would actually pick
    (single, double, triple byes). The "no byes" profile is included when the field is a clean
    power of two for that bracket size.
    """
    if n < 2:
        return []
    base = _ceil_log2(n)
    profiles: list[ByeProfile] = []
    seen: set[tuple[tuple[int, int], ...]] = set()
    for rounds in range(base, base + extra_rounds + 1):
        # Σ count[b]*(2**b - 1) over b>=1 must equal 2**rounds - n, with the round-1 entrants
        # (count[0]) even and non-negative.
        target = (1 << rounds) - n
        levels = list(range(1, min(max_bye_level, rounds - 1) + 1))
        for combo in _coin_combos(target, [(b, (1 << b) - 1) for b in levels], n):
            used = sum(c for _, c in combo)
            base_count = n - used
            # Round 1 needs at least one real match; a profile where every seed byes is just a
            # smaller bracket mislabelled (and is already listed at its true round count).
            if base_count < 2 or base_count % 2 != 0:
                continue
            counts = {b: c for b, c in combo if c > 0}
            if base_count:
                counts[0] = base_count
            key = tuple(sorted(counts.items()))
            if key in seen:
                continue
            seen.add(key)
            profiles.append(ByeProfile(rounds=rounds, counts=counts))
    profiles.sort(key=lambda p: (p.rounds, -p.doubles, -p.singles))
    return profiles


def _coin_combos(
    target: int, coins: list[tuple[int, int]], cap: int
) -> list[list[tuple[int, int]]]:
    """All ways to make ``target`` from ``coins`` (bye_level, value), using <= ``cap`` coins total."""
    results: list[list[tuple[int, int]]] = []

    def recurse(idx: int, remaining: int, used: int, acc: list[tuple[int, int]]) -> None:
        if remaining == 0:
            results.append(list(acc))
            return
        if idx >= len(coins):
            return
        level, value = coins[idx]
        max_count = remaining // value if value else 0
        for count in range(max_count + 1):
            if used + count > cap:
                break
            acc.append((level, count))
            recurse(idx + 1, remaining - count * value, used + count, acc)
            acc.pop()

    recurse(0, target, 0, [])
    return results


# --------------------------------------------------------------------------------------
# Plan: a tiling byes map -> abstract bracket tree in standard seed order
# --------------------------------------------------------------------------------------


def _split_region(seeds: list[int], byes: dict[int, int], half: int) -> tuple[list[int], list[int]]:
    """Split a region's seeds (best-first) into two equal-capacity halves in standard order.

    Each seed consumes ``2**byes[seed]`` capacity; both halves must reach ``half``. Seeds are
    assigned in the standard inner-outer side pattern (A, B, B, A, A, B, B, A, ...) so the top
    seed and second seed fall on opposite sides; a block that would overflow its preferred side
    spills to the other, which only ever happens for the small trailing blocks.
    """
    a: list[int] = []
    b: list[int] = []
    a_sum = b_sum = 0
    for i, seed in enumerate(seeds):
        block = 1 << byes[seed]
        prefer_a = i % 4 in (0, 3)
        if prefer_a and a_sum + block <= half:
            a.append(seed)
            a_sum += block
        elif not prefer_a and b_sum + block <= half:
            b.append(seed)
            b_sum += block
        elif a_sum + block <= half:
            a.append(seed)
            a_sum += block
        else:
            b.append(seed)
            b_sum += block
    if a_sum != half or b_sum != half:  # pragma: no cover - guarded by Kraft tiling upstream
        raise ValidationError("Byes do not tile a balanced bracket; complete them first.")
    return a, b


def _region(seeds: list[int], byes: dict[int, int], height: int) -> ByeNode:
    if len(seeds) == 1:
        seed = seeds[0]
        if byes[seed] != height:
            raise ValidationError(  # pragma: no cover - guarded by Kraft tiling upstream
                f"Seed {seed} with {byes[seed]} byes does not fit a height-{height} region."
            )
        return ("seed", seed)
    left, right = _split_region(seeds, byes, 1 << (height - 1))
    return ("match", height, _region(left, byes, height - 1), _region(right, byes, height - 1))


def build_bye_plan(byes: dict[int, int]) -> ByeNode:
    """Turn a tiling seed -> byes map into an abstract bracket tree.

    The tree is in standard seed order: ``("match", round, left, right)`` nodes and
    ``("seed", seed_number)`` leaves (a leaf byes through every round below its parent). The
    caller emits real matches by walking it left-first, which keeps sibling matches adjacent and
    seeds in their correct halves. Raises if ``byes`` does not tile a perfect bracket.
    """
    seeds = sorted(byes)  # ascending seed number == best-first
    total = sum(1 << byes[s] for s in seeds)
    if not is_power_of_2(total):
        raise ValidationError(
            "byes do not tile a power-of-two bracket; call complete_bye_rounds() first."
        )
    return _region(seeds, byes, log2_int(total))
