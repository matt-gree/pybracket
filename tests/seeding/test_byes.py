from __future__ import annotations

import pybracket as pb
import pytest
from pybracket.seeding.byes import build_bye_plan
from pybracket.utils.math import is_power_of_2

from tests.helpers import make_participants


def _kraft(byes: dict[int, int]) -> int:
    return sum(1 << b for b in byes.values())


# --- complete_bye_rounds -------------------------------------------------------------------


def test_completion_tiles_a_power_of_two() -> None:
    result = pb.complete_bye_rounds(16, {1: 2, 2: 2, 3: 2, 4: 2})
    assert is_power_of_2(_kraft(result.completed))
    assert _kraft(result.completed) == 1 << result.rounds


def test_completion_adds_single_byes_below_the_double_byes() -> None:
    result = pb.complete_bye_rounds(16, {1: 2, 2: 2, 3: 2, 4: 2})
    assert result.added == {5: 1, 6: 1, 7: 1, 8: 1}
    assert result.changed is True


def test_completion_leaves_a_tiling_request_untouched() -> None:
    tiered = {1: 2, 2: 2, 3: 2, 4: 2, 5: 1, 6: 1, 7: 1, 8: 1}
    result = pb.complete_bye_rounds(16, tiered)
    assert result.added == {}
    assert result.changed is False


def test_completion_respects_requested_minimums() -> None:
    result = pb.complete_bye_rounds(16, {1: 2, 2: 2})
    for seed, requested in {1: 2, 2: 2}.items():
        assert result.completed[seed] >= requested


def test_completion_reproduces_single_gauntlet_ladder() -> None:
    # byes = n - k - 1 is the gauntlet point on the continuum and already tiles.
    n = 8
    result = pb.complete_bye_rounds(n, {k: n - k - 1 for k in range(1, n - 1)})
    assert result.added == {}
    assert result.completed == {1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1, 7: 0, 8: 0}


@pytest.mark.parametrize("bad", [{1: 3}, {1: 5}, {1: 1, 2: 1, 3: 1, 4: 1}])
def test_completion_rejects_byes_the_field_cannot_carry(bad: dict[int, int]) -> None:
    with pytest.raises(pb.ValidationError):
        pb.complete_bye_rounds(4, bad)


def test_completion_rejects_non_monotonic_request() -> None:
    with pytest.raises(pb.ValidationError):
        pb.complete_bye_rounds(8, {1: 1, 2: 2})


# --- allowable_bye_options -----------------------------------------------------------------


@pytest.mark.parametrize("n", [8, 12, 14, 16, 11])
def test_every_option_is_a_real_tiling(n: int) -> None:
    for profile in pb.allowable_bye_options(n):
        byes = profile.to_bye_rounds()
        assert sum(byes.values()) >= 0
        # Expanding the level counts gives one bye per seed and tiles a 2**rounds bracket.
        assert len(byes) == n
        assert _kraft(byes) == 1 << profile.rounds
        # Every option must actually build (completion is a no-op on a tiling config).
        assert pb.complete_bye_rounds(n, byes).added == {}


def test_options_include_the_big_twelve_shape_for_fourteen() -> None:
    options = pb.allowable_bye_options(14)
    shapes = {(p.doubles, p.singles, p.counts.get(0, 0)) for p in options}
    assert (4, 6, 4) in shapes  # 4 double byes, 6 single byes, 4 play-in games' worth


def test_small_or_empty_fields_have_no_options() -> None:
    assert pb.allowable_bye_options(1) == []


# --- build_bye_plan ------------------------------------------------------------------------


def test_plan_requires_a_tiling_map() -> None:
    with pytest.raises(pb.ValidationError):
        build_bye_plan({1: 2, 2: 0, 3: 0})  # kraft = 6, not a power of two


def test_no_bye_plan_reproduces_standard_first_round_pairings() -> None:
    # With no byes, the bye builder and the classic seed_slots builder agree on round 1.
    classic = pb.generate_single_elim(make_participants(8))
    byed = pb.generate_single_elim(make_participants(8), bye_rounds={})

    def first_round_pairs(bracket: pb.Bracket) -> set[frozenset[int]]:
        round1 = next(r for r in bracket.rounds if r.number == 1)
        return {
            frozenset((m.participant1_id, m.participant2_id))
            for m in bracket.matches
            if m.id in round1.match_ids
        }

    assert first_round_pairs(classic) == first_round_pairs(byed)
