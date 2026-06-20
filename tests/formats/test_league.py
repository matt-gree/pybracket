from __future__ import annotations

from collections import Counter

import pybracket as pb
import pytest

from tests.helpers import make_participants, simulate


def test_single_round_robin_structure() -> None:
    lg = pb.generate_league(make_participants(6))
    assert lg.format == "league"
    assert len(lg.rounds) == 5  # n-1 matchweeks
    assert len(lg.matches) == 15  # n*(n-1)/2 pairings
    assert all(len(r.match_ids) == 3 for r in lg.rounds)


def test_every_pairing_played_once() -> None:
    lg = pb.generate_league(make_participants(6))
    pairs = Counter(
        frozenset((m.participant1_id, m.participant2_id)) for m in lg.matches
    )
    assert len(pairs) == 15
    assert all(count == 1 for count in pairs.values())


def test_schedule_metadata_written() -> None:
    lg = pb.generate_league(make_participants(4))
    for m in lg.matches:
        assert m.metadata["matchweek"] == m.round_number
        assert {m.metadata["home_id"], m.metadata["away_id"]} == {
            m.participant1_id,
            m.participant2_id,
        }


def test_home_away_is_balanced() -> None:
    lg = pb.generate_league(make_participants(8))
    homes = Counter(m.metadata["home_id"] for m in lg.matches)
    # 8 teams play 7 games each -> 3 or 4 home apiece (off by at most one).
    assert max(homes.values()) - min(homes.values()) <= 1


def test_odd_field_byes_each_matchweek() -> None:
    lg = pb.generate_league(make_participants(5))
    # 5 teams -> 5 matchweeks, 2 matches each (one team rests).
    assert len(lg.rounds) == 5
    assert all(len(r.match_ids) == 2 for r in lg.rounds)
    pairs = {frozenset((m.participant1_id, m.participant2_id)) for m in lg.matches}
    assert len(pairs) == 10  # 5*4/2


def test_standings_with_points_and_draws() -> None:
    lg = pb.generate_league(make_participants(4), points=pb.PointsSystem(3, 1, 0))
    # P1 beats everyone; one draw between P2 and P3; P4 loses the rest.
    ids = {frozenset((m.participant1_id, m.participant2_id)): m.id for m in lg.matches}
    for pair, mid in ids.items():
        a, b = sorted(pair)
        lg = pb.report_draw(lg, mid) if {a, b} == {2, 3} else pb.report_result(lg, mid, a)
    assert pb.is_complete(lg)
    s = {x.participant_id: x for x in pb.get_standings(lg)}
    assert s[1].points == 9.0  # 3 wins
    assert s[2].draws == 1 and s[3].draws == 1
    assert pb.get_winner(lg).id == 1


def test_placements_from_standings() -> None:
    lg = simulate(pb.generate_league(make_participants(6)))
    placements = pb.get_placements(lg)
    assert placements[0].participant_id == 1  # lower seed wins -> P1 first
    assert [p.position for p in placements] == [1, 2, 3, 4, 5, 6]


def test_best_of_applied() -> None:
    lg = pb.generate_league(make_participants(4), best_of=3)
    assert all(m.best_of == 3 for m in lg.matches)


def test_even_best_of_requires_draws() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_league(make_participants(4), best_of=2)
    lg = pb.generate_league(
        make_participants(4), best_of=2, points=pb.PointsSystem(draws_allowed=True)
    )
    assert all(m.best_of == 2 for m in lg.matches)


def test_invalid_schedule_rejected() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_league(make_participants(4), schedule="zigzag")


def test_reseed_before_play() -> None:
    lg = pb.generate_league(make_participants(4), points=pb.PointsSystem())
    rs = pb.reseed(lg, [4, 3, 2, 1])
    assert rs.format == "league"
    assert [p.id for p in rs.participants] == [4, 3, 2, 1]


def test_reseed_after_play_raises() -> None:
    lg = pb.generate_league(make_participants(4))
    m = pb.get_ready_matches(lg)[0]
    lg = pb.report_result(lg, m.id, m.participant1_id)
    with pytest.raises(pb.BracketStateError):
        pb.reseed(lg, [4, 3, 2, 1])


def test_serialization_roundtrip() -> None:
    lg = simulate(pb.generate_league(make_participants(6), points=pb.PointsSystem(3, 1, 0)))
    rb = pb.bracket_from_json(pb.bracket_to_json(lg))
    assert rb.format == "league"
    assert rb.config["points_system"] == pb.PointsSystem(3, 1, 0)
    assert [s.participant_id for s in pb.get_standings(rb)] == [
        s.participant_id for s in pb.get_standings(lg)
    ]
    assert rb.matches[0].metadata["matchweek"] == 1


def test_divisions_split_into_one_bracket() -> None:
    lg = pb.generate_league(make_participants(8), divisions=2)
    rosters = pb.league_divisions(lg)
    assert len(rosters) == 2
    assert sorted(pid for r in rosters for pid in r) == list(range(1, 9))
    # 2 divisions of 4 -> 6 intra-division games each, all in one bracket.
    assert len(lg.matches) == 12
    div_of = {pid: i for i, r in enumerate(rosters) for pid in r}
    assert all(
        div_of[m.participant1_id] == div_of[m.participant2_id] == m.metadata["division"]
        for m in lg.matches
    )


def test_snake_division_assignment() -> None:
    rosters = pb.league_divisions(pb.generate_league(make_participants(8), divisions=2))
    # snake: seeds 1,4,5,8 -> div A; 2,3,6,7 -> div B
    assert rosters[0] == [1, 4, 5, 8]
    assert rosters[1] == [2, 3, 6, 7]


def test_division_standings_filter_and_overall() -> None:
    lg = simulate(
        pb.generate_league(make_participants(8), divisions=2, points=pb.PointsSystem(3, 1, 0))
    )
    overall = pb.get_standings(lg)
    assert len(overall) == 8
    d0 = pb.division_standings(lg, 0)
    assert {s.participant_id for s in d0} == {1, 4, 5, 8}
    assert [s.rank for s in d0] == [1, 2, 3, 4]  # re-ranked within the division


def test_invalid_division_count_rejected() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_league(make_participants(8), divisions=0)
    with pytest.raises(pb.ValidationError):
        pb.generate_league(make_participants(4), divisions=3)  # <2 teams per division


def test_division_standings_out_of_range() -> None:
    lg = pb.generate_league(make_participants(8), divisions=2)
    with pytest.raises(pb.ValidationError):
        pb.division_standings(lg, 2)


def test_divisions_serialization_roundtrip() -> None:
    lg = pb.generate_league(make_participants(8), divisions=2, points=pb.PointsSystem(3, 1, 0))
    rb = pb.bracket_from_json(pb.bracket_to_json(lg))
    assert pb.league_divisions(rb) == pb.league_divisions(lg)
    assert all(m.metadata.get("division") is not None for m in rb.matches)


def test_divisioned_league_phase_to_playoff() -> None:
    # 2-division league -> each division winner into a final.
    t = pb.generate_tournament(
        make_participants(8),
        [
            pb.PhaseSpec("season", "league", groups=2,
                         config={"points_system": pb.PointsSystem(3, 1, 0)}),
            pb.PhaseSpec("final", "single_elim",
                         entrants=pb.Qualification(sources=pb.top_of_each_group("season", 1))),
        ],
    )
    # one bracket, internally divided (not two separate brackets)
    assert len(t.phases[0].brackets) == 1
    season = simulate(t.phases[0].brackets[0])
    t.phases[0].brackets[0] = season
    d0 = pb.phase_results(t, "season", group=0)
    d1 = pb.phase_results(t, "season", group=1)
    assert d0[0].rank == 1 and d1[0].rank == 1
    assert {d0[0].participant_id, d1[0].participant_id} == {1, 2}  # the two division winners
    assert len(pb.phase_results(t, "season")) == 8


def test_league_phase_feeds_a_playoff() -> None:
    # league season -> top 4 into a single-elim playoff (the season->playoffs shape).
    t = pb.generate_tournament(
        make_participants(8),
        [
            pb.PhaseSpec("season", "league", config={"points_system": pb.PointsSystem(3, 1, 0)}),
            pb.PhaseSpec(
                "playoffs",
                "single_elim",
                entrants=pb.Qualification(sources=pb.top("season", 4)),
            ),
        ],
    )
    season = t.phases[0].brackets[0]
    assert season.format == "league"
    season = simulate(season)
    t.phases[0].brackets[0] = season
    results = pb.phase_results(t, "season")
    assert len(results) == 8
    assert results[0].rank == 1
