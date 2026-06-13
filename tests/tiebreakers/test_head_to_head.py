from __future__ import annotations

from pybracket import (
    AdvancementType,
    Bracket,
    BracketSide,
    BracketState,
    Match,
    MatchStatus,
    Participant,
    get_standings,
)
from pybracket.tiebreakers.base import StandingsContext
from pybracket.tiebreakers.head_to_head import HeadToHeadTiebreaker


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


def test_head_to_head_breaks_a_two_way_tie() -> None:
    # Players 2 and 3 both finish 2-1, but 2 beat 3 head-to-head.
    matches = [
        completed(1, 2, 1, 2),
        completed(2, 2, 3, 2),  # 2 beats 3 head-to-head
        completed(3, 3, 1, 3),
        completed(4, 3, 4, 3),
        completed(5, 4, 2, 4),
    ]
    participants = [Participant(id=i, seed=i, name=f"P{i}") for i in range(1, 5)]
    bracket = Bracket(
        format="round_robin",
        state=BracketState.COMPLETE,
        participants=participants,
        matches=matches,
        rounds=[],
        config={"tiebreakers": [{"type": "win_count"}, {"type": "head_to_head"}]},
    )
    standings = {s.participant_id: s for s in get_standings(bracket)}
    assert standings[2].wins == standings[3].wins == 2
    assert standings[2].rank < standings[3].rank  # 2 ranked above 3 on head-to-head


def test_head_to_head_net_score() -> None:
    matches = [completed(1, 1, 2, 1), completed(2, 1, 2, 1), completed(3, 2, 1, 2)]
    ctx = StandingsContext(matches, [1, 2])
    tb = HeadToHeadTiebreaker()
    assert tb.score(1, ctx) == 1.0  # won 2, lost 1 vs player 2
    assert tb.score(2, ctx) == -1.0
