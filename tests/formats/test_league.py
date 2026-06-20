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


def test_double_round_robin_plays_each_pairing_twice() -> None:
    lg = pb.generate_league(make_participants(4), double=True)
    assert len(lg.rounds) == 6  # 2 * (n-1)
    assert len(lg.matches) == 12
    pairs = Counter(frozenset((m.participant1_id, m.participant2_id)) for m in lg.matches)
    assert all(count == 2 for count in pairs.values())


def test_double_round_robin_balances_and_swaps_venues() -> None:
    lg = pb.generate_league(make_participants(4), double=True)
    homes = Counter(m.metadata["home_id"] for m in lg.matches)
    assert set(homes.values()) == {3}  # each team hosts exactly half of its 6 games
    venues: dict[frozenset, set] = {}
    for m in lg.matches:
        venues.setdefault(frozenset((m.participant1_id, m.participant2_id)), set()).add(
            m.metadata["home_id"]
        )
    assert all(len(hosts) == 2 for hosts in venues.values())  # each meeting at a different venue


def test_double_with_divisions() -> None:
    lg = pb.generate_league(make_participants(8), divisions=2, double=True)
    assert lg.config["double"] is True
    assert len(lg.matches) == 24  # 2 divisions * 12 (double RR of 4)


def test_reseed_preserves_divisions_and_double() -> None:
    lg = pb.generate_league(
        make_participants(8), divisions=2, double=True, points=pb.PointsSystem()
    )
    rs = pb.reseed(lg, list(range(8, 0, -1)))
    assert len(pb.league_divisions(rs)) == 2
    assert rs.config["double"] is True
    assert len(rs.matches) == 24


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


def _cross(lg: pb.Bracket) -> list[pb.Match]:
    return [m for m in lg.matches if m.metadata["division"] is None]


def _cross_degrees(lg: pb.Bracket) -> Counter:
    deg: Counter = Counter()
    for m in _cross(lg):
        deg[m.participant1_id] += 1
        deg[m.participant2_id] += 1
    return deg


@pytest.mark.parametrize("pairing", ["balanced", "top_seed_favored", "random"])
def test_cross_division_gives_each_team_its_games(pairing: str) -> None:
    cd = pb.CrossDivision(games_per_team=2, pairing=pairing, seed=1)
    lg = pb.generate_league(
        make_participants(8), divisions=2, points=pb.PointsSystem(), cross_division=cd
    )
    rosters = pb.league_divisions(lg)
    div_of = {pid: i for i, r in enumerate(rosters) for pid in r}
    cross = _cross(lg)
    assert all(div_of[m.participant1_id] != div_of[m.participant2_id] for m in cross)
    assert all(deg == 2 for deg in _cross_degrees(lg).values())


def test_cross_division_round_robin_plays_everyone() -> None:
    lg = pb.generate_league(
        make_participants(8),
        divisions=2,
        points=pb.PointsSystem(),
        cross_division=pb.CrossDivision(pairing="round_robin"),
    )
    # each team plays all 4 of the other division
    assert all(deg == 4 for deg in _cross_degrees(lg).values())
    assert len(_cross(lg)) == 16


def test_cross_division_balanced_is_rank_symmetric() -> None:
    lg = pb.generate_league(
        make_participants(8),
        divisions=2,
        points=pb.PointsSystem(),
        cross_division=pb.CrossDivision(games_per_team=1, pairing="balanced"),
    )
    # divisions [[1,4,5,8],[2,3,6,7]] -> same-rank pairs: 1-2, 4-3, 5-6, 8-7
    pairs = {frozenset((m.participant1_id, m.participant2_id)) for m in _cross(lg)}
    assert pairs == {frozenset((1, 2)), frozenset((4, 3)), frozenset((5, 6)), frozenset((8, 7))}


def test_cross_division_repeat_home_away_doubles() -> None:
    lg = pb.generate_league(
        make_participants(8),
        divisions=2,
        points=pb.PointsSystem(),
        cross_division=pb.CrossDivision(games_per_team=1, pairing="balanced", repeat_home_away=True),
    )
    assert all(deg == 2 for deg in _cross_degrees(lg).values())  # each cross pairing twice


def test_cross_division_no_team_double_booked_in_a_week() -> None:
    lg = pb.generate_league(
        make_participants(8),
        divisions=2,
        points=pb.PointsSystem(),
        cross_division=pb.CrossDivision(games_per_team=3, pairing="round_robin"),
    )
    for r in lg.rounds:
        teams = [
            pid
            for mid in r.match_ids
            for pid in (pb.get_match(lg, mid).participant1_id, pb.get_match(lg, mid).participant2_id)
        ]
        assert len(teams) == len(set(teams))


def test_cross_division_random_is_reproducible() -> None:
    def cross_pairs(seed: int) -> set:
        lg = pb.generate_league(
            make_participants(8), divisions=2, points=pb.PointsSystem(),
            cross_division=pb.CrossDivision(2, "random", seed=seed),
        )
        return {frozenset((m.participant1_id, m.participant2_id)) for m in _cross(lg)}

    assert cross_pairs(7) == cross_pairs(7)


def test_cross_division_requires_two_divisions() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_league(make_participants(8), divisions=1, cross_division=pb.CrossDivision(2))


def test_cross_division_invalid_pairing_rejected() -> None:
    with pytest.raises(pb.ValidationError):
        pb.generate_league(
            make_participants(8), divisions=2, cross_division=pb.CrossDivision(2, "zigzag")
        )


def test_cross_division_serialization_and_play() -> None:
    lg = pb.generate_league(
        make_participants(8), divisions=2, points=pb.PointsSystem(3, 1, 0),
        cross_division=pb.CrossDivision(2, "balanced"),
    )
    rb = pb.bracket_from_json(pb.bracket_to_json(lg))
    assert rb.config["cross_division"] == pb.CrossDivision(2, "balanced")
    assert len(_cross(rb)) == len(_cross(lg))
    assert pb.is_complete(simulate(rb))


def test_cross_division_as_a_tournament_phase() -> None:
    t = pb.generate_tournament(
        make_participants(8),
        [
            pb.PhaseSpec("season", "league", groups=2, config={
                "points_system": pb.PointsSystem(3, 1, 0),
                "cross_division": pb.CrossDivision(1, "balanced"),
            }),
            pb.PhaseSpec("final", "single_elim",
                         entrants=pb.Qualification(sources=pb.top_of_each_group("season", 1))),
        ],
    )
    lg = t.phases[0].brackets[0]
    assert any(m.metadata["division"] is None for m in lg.matches)  # cross games exist
    t.phases[0].brackets[0] = simulate(lg)
    assert len(pb.phase_results(t, "season", group=0)) == 4


def test_transforms_compose() -> None:
    lg = pb.generate_league(make_participants(8), divisions=2)
    lg = pb.with_home_away(lg)
    lg = pb.with_points(lg, pb.PointsSystem(3, 1, 0))
    lg = pb.with_best_of(lg, 3)
    lg = pb.with_cross_division(lg, pb.CrossDivision(1, "balanced"))
    assert lg.config["double"] is True
    assert lg.config["best_of"] == 3
    assert lg.config["points_system"] == pb.PointsSystem(3, 1, 0)
    assert lg.config["cross_division"] == pb.CrossDivision(1, "balanced")
    assert len(pb.league_divisions(lg)) == 2
    assert all(m.best_of == 3 for m in lg.matches)


def test_with_home_away_builds_double() -> None:
    lg = pb.with_home_away(pb.generate_league(make_participants(4)))
    assert lg.config["double"] is True
    assert len(lg.matches) == 12  # double RR of 4


def test_transform_after_results_raises() -> None:
    lg = pb.generate_league(make_participants(4), points=pb.PointsSystem())
    m = pb.get_ready_matches(lg)[0]
    lg = pb.report_result(lg, m.id, m.participant1_id)
    with pytest.raises(pb.BracketStateError):
        pb.with_home_away(lg)


def test_transform_on_non_league_raises() -> None:
    with pytest.raises(pb.ValidationError):
        pb.with_home_away(pb.generate_round_robin(make_participants(4)))


def test_league_schedule_view() -> None:
    lg = pb.generate_league(
        make_participants(8), divisions=2, points=pb.PointsSystem(),
        cross_division=pb.CrossDivision(1, "balanced"),
    )
    sched = pb.league_schedule(lg)
    assert [w.number for w in sched] == sorted(w.number for w in sched)
    # every match appears exactly once across the matchweeks
    fixture_ids = {f.match_id for w in sched for f in w.fixtures}
    assert fixture_ids == {m.id for m in lg.matches}
    # a fixture records home/away and division (None for cross games)
    sample = sched[0].fixtures[0]
    assert isinstance(sample, pb.Fixture)
    assert {sample.home_id, sample.away_id} == {
        m.participant1_id for m in lg.matches if m.id == sample.match_id
    } | {m.participant2_id for m in lg.matches if m.id == sample.match_id}
    assert any(f.division is None for w in sched for f in w.fixtures)  # cross games present


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
