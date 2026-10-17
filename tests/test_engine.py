import pytest

from app.services.engine import MatchError
from app.services.stats import innings_scorecard, live_state, match_summary
from app.services.undo import undo_last_ball
from tests.conftest import Builder, ball, start


def test_basic_runs_and_strike_rotation():
    e = Builder().add(start(), ball(1), ball(4), ball(0)).engine()
    inn = e.current
    assert inn.runs == 5
    assert inn.legal_balls == 3
    assert inn.batters["t0p0"].runs == 1 and inn.batters["t0p0"].balls == 1
    assert inn.batters["t0p1"].runs == 4 and inn.batters["t0p1"].fours == 1
    assert inn.striker == "t0p1"  # single rotated strike, four did not


def test_additional_runs_are_combined_on_one_delivery():
    e = Builder().add(start(), ball(2, additional=[1]), ball(4, additional=[2])).engine()
    inn = e.current
    assert inn.runs == 9
    # 2+1 = 3 (odd) rotates strike; second ball faced by t0p1
    assert inn.batters["t0p0"].runs == 3
    assert inn.batters["t0p1"].runs == 6
    assert inn.batters["t0p1"].fours == 1 and inn.batters["t0p1"].sixes == 0
    assert [d.label for d in inn.deliveries] == ["2+1", "4+2"]


def test_explicit_striker_selection_overrides_rotation():
    e = Builder().add(start(), ball(1), ball(2, striker="t0p0")).engine()
    assert e.current.batters["t0p0"].runs == 3
    assert e.current.batters["t0p0"].balls == 2


def test_over_completion_requires_new_bowler_and_swaps_strike():
    b = Builder().add(start(), *[ball(0) for _ in range(6)])
    e = b.engine()
    inn = e.current
    assert inn.bowler is None
    assert e.next_action == "select_bowler"
    assert inn.striker == "t0p1"
    assert inn.bowlers["t1p0"].balls == 6
    with pytest.raises(MatchError):
        b.add(ball(1)).engine()


def test_extras_before_last_over_are_legal_deliveries_worth_two():
    e = Builder(overs=2).add(
        start(),
        ball(0, extra="wide"),
        ball(2, extra="wide"),
        ball(4, extra="no_ball"),
        ball(1, extra="bye"),
        ball(2, extra="leg_bye"),
    ).engine()
    inn = e.current
    assert inn.extras == {"wide": 6, "no_ball": 2, "bye": 1, "leg_bye": 2}
    assert inn.runs == 2 + 4 + 6 + 1 + 2
    assert inn.legal_balls == 5
    bowler = inn.bowlers["t1p0"]
    assert bowler.runs == 2 + 4 + 6  # byes and leg byes are not charged to the bowler
    assert bowler.balls == 5 and bowler.wides == 2 and bowler.no_balls == 1
    assert inn.batters["t0p0"].runs == 4  # runs off the bat from the no ball
    assert inn.batters["t0p0"].balls == 4


def test_extras_in_last_over_are_rebowled_and_worth_one():
    b = Builder(overs=2).add(start(), *[ball(0) for _ in range(6)], {"type": "bowler", "bowler": "t1p1"})
    e = b.add(ball(0, extra="wide"), ball(0, extra="no_ball")).engine()
    inn = e.current
    assert inn.runs == 2
    assert inn.legal_balls == 6
    assert inn.batters["t0p1"].balls == 1  # wide not faced, no ball faced


def test_configurable_penalty_runs():
    e = Builder(wide_runs=3, no_ball_runs=4).add(start(), ball(0, extra="wide"), ball(0, extra="no_ball")).engine()
    assert e.current.runs == 7
    assert Builder(overs=1, last_over_extra_runs=2).add(start(), ball(0, extra="wide")).engine().current.runs == 2


def test_wicket_records_dismissal_and_prompts_replacement():
    b = Builder().add(start(), ball(2), ball(0, dismissal={"type": "bowled"}))
    e = b.engine()
    inn = e.current
    assert inn.wickets == 1
    assert inn.batters["t0p0"].status == "out"
    assert inn.batters["t0p0"].dismissal == "b Bravo0"
    assert inn.bowlers["t1p0"].wickets == 1
    assert inn.fall_of_wickets[0]["runs"] == 2
    assert e.next_action == "select_batsman"
    with pytest.raises(MatchError):
        Builder().add(start(), ball(0, dismissal={"type": "bowled"}), ball(1)).engine()

    e = b.add({"type": "new_batsman", "batsman": "t0p2"}).engine()
    assert e.current.striker == "t0p2"
    assert e.next_action == "ball"


def test_run_out_not_credited_to_bowler_and_can_be_non_striker():
    e = Builder().add(start(), ball(1, dismissal={"type": "run_out", "batsman": "t0p1"})).engine()
    inn = e.current
    assert inn.batters["t0p1"].status == "out"
    assert inn.bowlers["t1p0"].wickets == 0
    assert inn.runs == 1


def test_fielders_recorded_on_caught_and_run_out():
    b = Builder().add(
        start(),
        ball(0, dismissal={"type": "caught", "fielders": ["t1p2"]}),
        {"type": "new_batsman", "batsman": "t0p2"},
        ball(1, dismissal={"type": "run_out", "batsman": "t0p1", "fielders": ["t1p1", "t1p3"]}),
        {"type": "new_batsman", "batsman": "t0p3"},
    )
    batters = b.engine().current.batters
    assert batters["t0p0"].dismissal == "c Bravo2 b Bravo0"
    assert batters["t0p1"].dismissal == "run out (Bravo1 / Bravo3)"
    e = Builder().add(start(), ball(0, dismissal={"type": "caught", "fielders": ["t1p0"]})).engine()
    assert e.current.batters["t0p0"].dismissal == "c & b Bravo0"
    e = Builder().add(start(), ball(0, dismissal={"type": "run_out", "fielders": ["t1p1"]})).engine()
    assert e.current.batters["t0p0"].dismissal == "run out (Bravo1)"


def test_stumped_records_keeper_and_credits_bowler():
    e = Builder().add(start(), ball(0, dismissal={"type": "stumped", "fielders": ["t1p2"]})).engine()
    assert e.current.batters["t0p0"].dismissal == "st Bravo2 b Bravo0"
    assert e.current.bowlers["t1p0"].wickets == 1


def test_invalid_fielders_rejected():
    with pytest.raises(MatchError):
        Builder().add(start(), ball(0, dismissal={"type": "caught", "fielders": ["t1p1", "t1p2"]})).engine()
    with pytest.raises(MatchError):
        Builder().add(start(), ball(0, dismissal={"type": "caught", "fielders": ["t0p2"]})).engine()
    with pytest.raises(MatchError):
        Builder().add(start(), ball(0, dismissal={"type": "bowled", "fielders": ["t1p1"]})).engine()


def test_bowled_must_be_striker():
    with pytest.raises(MatchError):
        Builder().add(start(), ball(0, dismissal={"type": "bowled", "batsman": "t0p1"})).engine()


def test_retired_batsman_is_not_out_and_can_return():
    b = Builder().add(
        start(),
        ball(4),
        ball(0, dismissal={"type": "retired"}),
        {"type": "new_batsman", "batsman": "t0p2"},
    )
    e = b.engine()
    inn = e.current
    assert inn.wickets == 0
    assert inn.batters["t0p0"].status == "retired"
    available = live_state(e)["available_batsmen"]
    assert {"id": "t0p0", "name": "Alpha0", "retired": True} in available

    e = b.add(
        {"type": "retire", "batsman": "t0p1"},
        {"type": "new_batsman", "batsman": "t0p0"},
        ball(2, striker="t0p0"),
    ).engine()
    inn = e.current
    assert inn.batters["t0p0"].status == "batting"
    assert inn.batters["t0p0"].runs == 6
    card = innings_scorecard(e, inn)
    assert card["retired"] == ["Alpha1"]


def test_retire_both_batsmen_then_two_new_batsmen():
    b = Builder().add(start(), ball(1), {"type": "retire", "batsman": "t0p0"}, {"type": "retire", "batsman": "t0p1"})
    e = b.engine()
    assert e.current.striker is None and e.current.non_striker is None
    assert e.current.wickets == 0 and e.next_action == "select_batsman"
    e = b.add({"type": "new_batsman", "batsman": "t0p2"}, {"type": "new_batsman", "batsman": "t0p3"}).engine()
    assert e.next_action == "ball"


def test_partnership_resets_on_new_batsman():
    b = Builder().add(start(), ball(3), ball(2, extra="wide"))
    assert b.engine().current.partnership_runs == 7
    assert b.engine().current.partnership_balls == 2
    e = b.add(ball(0, dismissal={"type": "caught"}), {"type": "new_batsman", "batsman": "t0p2"}, ball(1)).engine()
    assert e.current.partnership_runs == 1


def test_all_out_when_no_batsmen_remaining():
    e = Builder(players=3).add(
        start(),
        ball(0, dismissal={"type": "bowled"}),
        {"type": "new_batsman", "batsman": "t0p2"},
        ball(0, dismissal={"type": "bowled"}),
    ).engine()
    assert e.current.complete and e.current.end_reason == "all_out"
    assert e.next_action == "start_innings"


def test_innings_ends_after_overs_and_chase_and_result():
    first = [start(0)] + [ball(1) if i % 6 != 5 else ball(0) for i in range(6)]
    first.insert(7, {"type": "bowler", "bowler": "t1p1"})
    first += [ball(2) for _ in range(6)]
    b = Builder().add(*first)
    e = b.engine()
    assert e.innings[0].complete and e.innings[0].end_reason == "overs_complete"
    assert e.innings[0].runs == 17
    assert e.next_batting_team == 1

    b.add(start(1))
    e = b.engine()
    chase = live_state(e)["current"]["chase"]
    assert chase == {"target": 18, "runs_required": 18, "balls_remaining": 12, "required_run_rate": 9.0}

    b.add(ball(6), ball(6), ball(6))
    e = b.engine()
    assert e.is_complete
    assert e.current.end_reason == "target_reached"
    result = e.result()
    assert result["winner"] == 1
    assert result["text"] == "Bravo won by 3 wickets (9 balls remaining)"
    summary = match_summary(e)
    assert summary["top_batsman"]["runs"] == 18
    assert summary["team_scores"][0]["innings"] == ["17/0 (2.0)"]


def test_team_batting_first_wins_by_runs():
    b = Builder(overs=1).add(start(0), *[ball(2) for _ in range(6)], start(1), *[ball(1) for _ in range(6)])
    result = b.engine().result()
    assert result["text"] == "Alpha won by 6 runs"


def test_tie():
    b = Builder(overs=1).add(start(0), *[ball(1) for _ in range(6)], start(1), *[ball(1) for _ in range(6)])
    assert b.engine().result()["text"] == "Match tied"


def test_second_innings_must_be_other_team():
    b = Builder(overs=1).add(start(0), *[ball(0) for _ in range(6)], start(0))
    with pytest.raises(MatchError):
        b.engine()


def test_bowler_must_be_from_bowling_team():
    with pytest.raises(MatchError):
        Builder().add(start(), {"type": "bowler", "bowler": "t0p3"}).engine()


def test_undo_restores_exact_previous_state():
    base = Builder().add(start(), ball(1), ball(4, additional=[2]))
    before = live_state(base.engine())
    events_before = list(base.match["events"])

    base.add(ball(0, dismissal={"type": "caught"}), {"type": "new_batsman", "batsman": "t0p2"})
    base.match["events"] = undo_last_ball(base.match["events"])
    assert base.match["events"] == events_before
    assert live_state(base.engine()) == before


def test_undo_restores_retirement_and_over_end():
    b = Builder().add(start(), *[ball(1) for _ in range(5)])
    before = live_state(b.engine())
    b.add(ball(0, dismissal={"type": "retired"}), {"type": "new_batsman", "batsman": "t0p2"}, {"type": "bowler", "bowler": "t1p1"})
    b.match["events"] = undo_last_ball(b.match["events"])
    after = b.engine()
    assert live_state(after) == before
    assert after.current.batters["t0p0"].status == "batting"


def test_undo_reopens_completed_innings():
    b = Builder(overs=1).add(start(0), *[ball(1) for _ in range(6)], start(1))
    b.match["events"] = undo_last_ball(b.match["events"])
    e = b.engine()
    assert len(e.innings) == 1
    assert not e.current.complete
    assert e.current.legal_balls == 5


def test_undo_without_balls_removes_last_event_and_errors_when_empty():
    assert undo_last_ball([start()]) == []
    with pytest.raises(MatchError):
        undo_last_ball([])


def test_bowling_figures_and_economy():
    e = Builder(overs=2).add(start(), *[ball(1) for _ in range(6)], {"type": "bowler", "bowler": "t1p1"}, ball(4)).engine()
    card = innings_scorecard(e, e.current)
    figures = {b["id"]: b for b in card["bowling"]}
    assert figures["t1p0"]["overs"] == "1.0" and figures["t1p0"]["runs"] == 6 and figures["t1p0"]["economy"] == 6.0
    assert figures["t1p1"]["overs"] == "0.1" and figures["t1p1"]["economy"] == 24.0


def test_pairing_overs_keep_batsman_in_and_count_wickets():
    b = Builder(overs=2, players=4).add(
        start(),
        ball(0, striker="t0p0", dismissal={"type": "bowled"}),
        ball(0, striker="t0p0", dismissal={"type": "caught", "fielders": ["t1p1"]}),
        ball(1, striker="t0p0", dismissal={"type": "run_out", "batsman": "t0p1", "fielders": ["t1p2"]}),
    )
    b.match["settings"]["pairing_overs"] = 1
    e = b.engine()
    inn = e.current
    assert inn.wickets == 3 and inn.bowlers["t1p0"].wickets == 2
    assert inn.striker and inn.non_striker and e.next_action == "ball"
    assert inn.batters["t0p0"].status == "batting"
    assert inn.batters["t0p0"].pair_dismissals == ["b Bravo0", "c Bravo1 b Bravo0"]
    assert inn.batters["t0p1"].pair_dismissals == ["run out (Bravo2)"]
    assert live_state(e)["current"]["in_pairing"] is True


def test_dismissal_after_pairing_overs_removes_batsman():
    b = Builder(overs=2).add(
        start(), *[ball(0) for _ in range(6)], {"type": "bowler", "bowler": "t1p1"}, ball(0, dismissal={"type": "bowled"})
    )
    b.match["settings"]["pairing_overs"] = 1
    e = b.engine()
    assert e.next_action == "select_batsman"
    assert live_state(e)["current"]["in_pairing"] is False


def test_set_pairing_overs_event_and_undo_keeps_it():
    b = Builder(overs=4).add(start(), ball(1), {"type": "set_pairing_overs", "pairing_overs": 2})
    assert b.engine().pairing_overs == 2
    b.match["events"] = undo_last_ball(b.match["events"])
    assert b.engine().pairing_overs == 2


def test_set_overs_mid_innings_extends_and_shortens():
    b = Builder(overs=2).add(start(), *[ball(1) for _ in range(6)], {"type": "set_overs", "overs": 3})
    e = b.engine()
    assert e.overs == 3 and live_state(e)["overs"] == 3
    assert e.penalty_runs(e.current, "wide") == 2  # over 2 of 3 is no longer the last over

    e = b.add({"type": "set_overs", "overs": 1}).engine()
    assert e.current.complete and e.current.end_reason == "overs_complete"


def test_set_overs_cannot_go_below_balls_bowled():
    b = Builder(overs=4).add(start(), *[ball(1) for _ in range(6)], {"type": "bowler", "bowler": "t1p1"}, ball(0))
    with pytest.raises(MatchError):
        b.add({"type": "set_overs", "overs": 1}).engine()


def test_set_overs_between_innings_changes_chase():
    b = Builder(overs=1).add(start(0), *[ball(1) for _ in range(6)], {"type": "set_overs", "overs": 2}, start(1))
    chase = live_state(b.engine())["current"]["chase"]
    assert chase["balls_remaining"] == 12 and chase["target"] == 7


def test_undo_keeps_overs_change():
    b = Builder(overs=2).add(start(), ball(1), {"type": "set_overs", "overs": 5})
    b.match["events"] = undo_last_ball(b.match["events"])
    e = b.engine()
    assert e.overs == 5 and e.current.legal_balls == 0


def test_custom_run_values_accepted():
    e = Builder().add(start(), ball(8), ball(11)).engine()
    assert e.current.runs == 19
    assert e.current.batters["t0p0"].runs == 19
    assert e.current.striker == "t0p1"


def test_negative_runs():
    e = Builder().add(start(), ball(4), ball(-3), ball(-1)).engine()
    inn = e.current
    assert inn.runs == 0
    assert inn.batters["t0p0"].runs == 0 and inn.batters["t0p0"].balls == 3
    assert inn.striker == "t0p0"  # negative runs never rotate strike
    assert inn.bowlers["t1p0"].runs == 4
    assert [d.label for d in inn.deliveries] == ["4", "-3", "-1"]


def test_invalid_runs_rejected():
    with pytest.raises(MatchError):
        Builder().add(start(), ball(51)).engine()
    with pytest.raises(MatchError):
        Builder().add(start(), ball(-4)).engine()
    with pytest.raises(MatchError):
        Builder().add(start(), ball(1, additional=[0])).engine()
