from __future__ import annotations

import pybracket as pb
import pytest
from pybracket import BracketState

from tests.helpers import make_participants, simulate


def _play_pools(pools: pb.PoolsBracket) -> pb.PoolsBracket:
    pools.pools = [simulate(p) for p in pools.pools]
    return pools


def test_snake_assignment_sizes() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    assert [len(p.participants) for p in pools.pools] == [4, 4]
    # Snake: seeds 1,4,5,8 -> pool A; 2,3,6,7 -> pool B.
    pool_a = {p.seed for p in pools.pools[0].participants}
    assert pool_a == {1, 4, 5, 8}


def test_uneven_pools_extras_to_earliest() -> None:
    pools = pb.generate_pools(make_participants(10), num_pools=4, advancement_count=2)
    sizes = [len(p.participants) for p in pools.pools]
    assert sizes == [3, 3, 2, 2]
    assert pools.config["uneven_pools"] is True


def test_elimination_draft_until_reseed() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    assert pools.elimination.state is BracketState.DRAFT
    assert pools.elimination.matches == []


def test_reseed_requires_complete_pools() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    with pytest.raises(pb.BracketStateError):
        pb.reseed_pools_to_bracket(pools)


def test_full_pools_to_double_elim() -> None:
    pools = pb.generate_pools(
        make_participants(8), num_pools=2, advancement_count=2, bracket_format="double_elim"
    )
    pools = _play_pools(pools)
    pools = pb.reseed_pools_to_bracket(pools)
    assert pools.elimination.state is BracketState.PUBLISHED
    assert pools.elimination.format == "double_elim"
    assert len(pools.elimination.participants) == 4  # 2 pools * 2 advancing
    pools.elimination = simulate(pools.elimination)
    assert pb.is_complete(pools.elimination)


def test_full_pools_to_single_elim() -> None:
    pools = pb.generate_pools(
        make_participants(8), num_pools=2, advancement_count=2, bracket_format="single_elim"
    )
    pools = _play_pools(pools)
    pools = pb.reseed_pools_to_bracket(pools)
    assert pools.elimination.format == "single_elim"
    pools.elimination = simulate(pools.elimination)
    assert pb.get_winner(pools.elimination) is not None


def test_rematch_avoidance_no_same_pool_round_one() -> None:
    pools = pb.generate_pools(
        make_participants(16), num_pools=4, advancement_count=2, bracket_format="single_elim"
    )
    pool_of = {
        p.id: i for i, pool in enumerate(pools.pools) for p in pool.participants
    }
    pools = _play_pools(pools)
    pools = pb.reseed_pools_to_bracket(pools)
    round1 = [m for m in pools.elimination.matches if m.round_number == 1]
    for m in round1:
        if m.participant1_id is not None and m.participant2_id is not None:
            assert pool_of[m.participant1_id] != pool_of[m.participant2_id]


def test_manual_reseed_override() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    pools = _play_pools(pools)
    # Determine the advancing ids and feed an explicit order.
    advancers = []
    for pool in pools.pools:
        standings = pb.get_standings(pool)
        advancers.extend(s.participant_id for s in standings[:2])
    pools = pb.reseed_pools_to_bracket(pools, new_seed_order=advancers)
    assert len(pools.elimination.participants) == 4


def test_num_pools_must_be_positive() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_pools(make_participants(8), num_pools=0, advancement_count=1)


def test_advancement_count_must_be_positive() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_pools(make_participants(8), num_pools=2, advancement_count=0)


def test_advancement_count_cannot_exceed_pool_size() -> None:
    # 8 players over 2 pools = 4 each; advancing 5 is impossible.
    with pytest.raises(pb.ValidationError):
        pb.generate_pools(make_participants(8), num_pools=2, advancement_count=5)


def test_unsupported_elimination_format_rejected_at_reseed() -> None:
    pools = pb.generate_pools(
        make_participants(8), num_pools=2, advancement_count=2, bracket_format="round_robin"
    )
    pools = _play_pools(pools)
    with pytest.raises(pb.ValidationError):
        pb.reseed_pools_to_bracket(pools)


# --- DRAFT -> publish flow ----------------------------------------------------------------


def test_draft_pools_produces_draft_bracket() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    pools = _play_pools(pools)
    drafted = pb.draft_pools_to_bracket(pools)
    assert drafted.elimination.state is BracketState.DRAFT
    # The bracket is fully built (seeds placed) even though it is not yet live.
    assert len(drafted.elimination.matches) > 0
    assert len(drafted.elimination.participants) == 4


def test_draft_requires_complete_pools() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    with pytest.raises(pb.BracketStateError):
        pb.draft_pools_to_bracket(pools)


def test_publish_transitions_draft_to_published() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    pools = _play_pools(pools)
    drafted = pb.draft_pools_to_bracket(pools)
    published = pb.publish_bracket(drafted)
    assert published.elimination.state is BracketState.PUBLISHED
    # Drafting then publishing is playable to completion.
    published.elimination = simulate(published.elimination)
    assert pb.is_complete(published.elimination)


def test_publish_rejects_non_draft_bracket() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    pools = _play_pools(pools)
    published = pb.reseed_pools_to_bracket(pools)  # already PUBLISHED
    with pytest.raises(pb.BracketStateError):
        pb.publish_bracket(published)


def test_reseed_pools_is_draft_then_publish_alias() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    pools = _play_pools(pools)
    one_step = pb.reseed_pools_to_bracket(pools)
    two_step = pb.publish_bracket(pb.draft_pools_to_bracket(pools))
    assert one_step.elimination.state is BracketState.PUBLISHED
    # Same resulting bracket structure via either path.
    assert pb.bracket_to_dict(one_step.elimination) == pb.bracket_to_dict(two_step.elimination)


def test_draft_reorder_changes_seeding_before_publish() -> None:
    pools = pb.generate_pools(make_participants(8), num_pools=2, advancement_count=2)
    pools = _play_pools(pools)
    advancers = []
    for pool in pools.pools:
        standings = pb.get_standings(pool)
        advancers.extend(s.participant_id for s in standings[:2])

    drafted = pb.draft_pools_to_bracket(pools)
    first_default = [m for m in drafted.elimination.matches if m.round_number == 1][0]

    reordered = pb.draft_pools_to_bracket(pools, new_seed_order=list(reversed(advancers)))
    assert reordered.elimination.state is BracketState.DRAFT
    first_reordered = [m for m in reordered.elimination.matches if m.round_number == 1][0]
    # Reversing the seed order changes who lands in the first slot.
    assert (first_default.participant1_id, first_default.participant2_id) != (
        first_reordered.participant1_id,
        first_reordered.participant2_id,
    )
    published = pb.publish_bracket(reordered)
    published.elimination = simulate(published.elimination)
    assert pb.is_complete(published.elimination)
