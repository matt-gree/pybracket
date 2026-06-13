from __future__ import annotations

from pybracket import AdvancementType, BracketSide, Match, MatchStatus
from pybracket.tiebreakers.base import StandingsContext
from pybracket.tiebreakers.buchholz import BuchholzTiebreaker


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


# A hand-verified all-play-all among four players.
#   1 beats 2, 3, 4   -> 3 wins
#   2 beats 3, 4      -> 2 wins
#   3 beats 4         -> 1 win
#   4                 -> 0 wins
def _context() -> StandingsContext:
    matches = [
        completed(1, 1, 2, 1),
        completed(2, 1, 3, 1),
        completed(3, 1, 4, 1),
        completed(4, 2, 3, 2),
        completed(5, 2, 4, 2),
        completed(6, 3, 4, 3),
    ]
    return StandingsContext(matches, [1, 2, 3, 4])


def test_win_counts() -> None:
    ctx = _context()
    assert ctx.wins == {1: 3, 2: 2, 3: 1, 4: 0}


def test_buchholz_scores() -> None:
    ctx = _context()
    tb = BuchholzTiebreaker()
    # Buchholz = sum of opponents' win counts.
    assert tb.score(1, ctx) == 2 + 1 + 0  # opponents 2,3,4
    assert tb.score(2, ctx) == 3 + 1 + 0  # opponents 1,3,4
    assert tb.score(3, ctx) == 3 + 2 + 0  # opponents 1,2,4
    assert tb.score(4, ctx) == 3 + 2 + 1  # opponents 1,2,3


def test_truncated_buchholz_drops_lowest() -> None:
    ctx = _context()
    tb = BuchholzTiebreaker(truncated=True)
    assert tb.score(1, ctx) == 2 + 1  # drop the 0
    assert tb.score(2, ctx) == 3 + 1  # drop the 0
    assert tb.score(3, ctx) == 3 + 2  # drop the 0
    assert tb.score(4, ctx) == 3 + 2  # opp wins [3,2,1], drop the 1


def test_truncated_name() -> None:
    assert BuchholzTiebreaker(truncated=True).name == "buchholz_truncated"
    assert BuchholzTiebreaker().name == "buchholz"
