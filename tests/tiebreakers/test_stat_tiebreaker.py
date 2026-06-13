from __future__ import annotations

from pybracket import (
    AdvancementType,
    Bracket,
    BracketSide,
    BracketState,
    Match,
    MatchStatus,
    Participant,
    StatTiebreaker,
    get_standings,
)
from pybracket.tiebreakers.base import StandingsContext


def completed(match_id: int, p1: int, p2: int, winner: int) -> Match:
    return Match(
        id=match_id,
        round_number=1,
        bracket_side=BracketSide.WINNERS,
        participant1_id=p1,
        participant2_id=p2,
        winner_id=winner,
        loser_id=p2 if winner == p1 else p1,
        advancement_type=AdvancementType.RESULT,
        next_winner_match_id=None,
        next_loser_match_id=None,
        status=MatchStatus.COMPLETED,
    )


def test_stat_breaks_tie_higher_is_better() -> None:
    participants = [
        Participant(id=1, seed=1, name="P1", stats={"run_differential": 5}),
        Participant(id=2, seed=2, name="P2", stats={"run_differential": 12}),
    ]
    # Both 0-0 (no completed matches): the run differential decides.
    bracket = Bracket(
        format="round_robin",
        state=BracketState.COMPLETE,
        participants=participants,
        matches=[],
        rounds=[],
        config={"tiebreakers": [{"type": "win_count"}, {"type": "stat", "stat_key": "run_differential"}]},
    )
    standings = {s.participant_id: s for s in get_standings(bracket)}
    assert standings[2].rank < standings[1].rank  # higher run differential ranks first


def test_stat_lower_is_better() -> None:
    tb = StatTiebreaker("penalties", higher_is_better=False)
    participants = [
        Participant(id=1, seed=1, name="P1", stats={"penalties": 2}),
        Participant(id=2, seed=2, name="P2", stats={"penalties": 9}),
    ]
    tb.bind(participants)
    ctx = StandingsContext([], [1, 2])
    assert tb.score(1, ctx) > tb.score(2, ctx)  # fewer penalties scores higher


def test_stat_missing_value_uses_default() -> None:
    tb = StatTiebreaker("rating", default=1500.0)
    participants = [Participant(id=1, seed=1, name="P1", stats={})]
    tb.bind(participants)
    ctx = StandingsContext([], [1])
    assert tb.score(1, ctx) == 1500.0


def test_stat_to_spec_round_trip() -> None:
    tb = StatTiebreaker("glicko", higher_is_better=False, default=1000.0)
    assert tb.to_spec() == {
        "type": "stat",
        "stat_key": "glicko",
        "higher_is_better": False,
        "default": 1000.0,
    }
