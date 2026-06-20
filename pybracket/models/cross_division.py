from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["CrossDivision"]

PAIRINGS = frozenset({"balanced", "random", "top_seed_favored", "round_robin"})


@dataclass(frozen=True)
class CrossDivision:
    """Inter-division games layered on top of a divisioned league (only meaningful when D > 1).

    ``games_per_team`` is how many *distinct* other-division opponents each team plays (ignored
    for ``round_robin``, which plays them all). ``pairing`` chooses opponents:

    - ``balanced``         — opponents of matching within-division rank (rank-symmetric). Default.
    - ``top_seed_favored`` — top seeds steered apart (strong plays weak), an easier top slate.
    - ``random``           — uniformly random legal opponents, reproducible under ``seed``.
    - ``round_robin``      — every other-division team (full interleague).

    ``repeat_home_away`` plays each cross pairing twice with venues swapped.
    """

    games_per_team: int = 1
    pairing: str = "balanced"
    repeat_home_away: bool = False
    seed: int = 0

    def to_spec(self) -> dict[str, Any]:
        return {
            "games_per_team": self.games_per_team,
            "pairing": self.pairing,
            "repeat_home_away": self.repeat_home_away,
            "seed": self.seed,
        }

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> CrossDivision:
        return cls(
            games_per_team=int(spec.get("games_per_team", 1)),
            pairing=spec.get("pairing", "balanced"),
            repeat_home_away=bool(spec.get("repeat_home_away", False)),
            seed=int(spec.get("seed", 0)),
        )
