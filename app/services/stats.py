"""Statistics and scorecard views derived from a replayed MatchEngine."""

from typing import Any

from app.services.engine import Batter, Bowler, Delivery, Innings, MatchEngine, overs_str

RECENT_BALLS = 12


def strike_rate(runs: int, balls: int) -> float:
    return round(runs * 100 / balls, 2) if balls else 0.0


def economy(runs: int, balls: int, balls_per_over: int) -> float:
    return round(runs * balls_per_over / balls, 2) if balls else 0.0


def batter_view(engine: MatchEngine, b: Batter) -> dict[str, Any]:
    info = engine.player_info.get(b.player_id, {})
    return {
        "id": b.player_id,
        "name": info.get("name", b.player_id),
        "shirt": info.get("shirt"),
        "runs": b.runs,
        "balls": b.balls,
        "wides_faced": b.wides_faced,
        "fours": b.fours,
        "sixes": b.sixes,
        "strike_rate": strike_rate(b.runs, b.balls),
        "status": b.status,
        "dismissal": b.dismissal,
        "pair_dismissals": list(b.pair_dismissals),
    }


def bowler_view(engine: MatchEngine, bw: Bowler) -> dict[str, Any]:
    info = engine.player_info.get(bw.player_id, {})
    return {
        "id": bw.player_id,
        "name": info.get("name", bw.player_id),
        "shirt": info.get("shirt"),
        "overs": overs_str(bw.balls, engine.balls_per_over),
        "balls": bw.balls,
        "runs": bw.runs,
        "wickets": bw.wickets,
        "wides": bw.wides,
        "no_balls": bw.no_balls,
        "economy": economy(bw.runs, bw.balls, engine.balls_per_over),
    }


def chase_view(engine: MatchEngine, inn: Innings) -> dict[str, Any] | None:
    if inn.target is None:
        return None
    required = max(0, inn.target - inn.runs)
    balls_left = max(0, engine.total_balls - inn.legal_balls)
    rrr = round(required * engine.balls_per_over / balls_left, 2) if balls_left else None
    return {"target": inn.target, "runs_required": required, "balls_remaining": balls_left, "required_run_rate": rrr}


def delivery_view(engine: MatchEngine, d: Delivery) -> dict[str, Any]:
    return {
        "event_index": d.event_index,
        "over": d.over + 1,
        "label": d.label,
        "total": d.total,
        "striker": d.striker,
        "non_striker": d.non_striker,
        "striker_name": engine.player_name(d.striker),
        "non_striker_name": engine.player_name(d.non_striker),
        "bowler_name": engine.player_name(d.bowler),
    }


def innings_scorecard(engine: MatchEngine, inn: Innings) -> dict[str, Any]:
    batting = [batter_view(engine, b) for b in sorted(inn.batters.values(), key=lambda b: b.order)]
    for row in batting:
        if row["status"] == "batting":
            row["dismissal"] = "not out"
    batted = set(inn.batters)
    did_not_bat = [p["name"] for p in engine.team_players(inn.batting_team) if p["id"] not in batted]
    extras = dict(inn.extras)
    extras["total"] = sum(inn.extras.values())
    return {
        "number": inn.number,
        "batting_team": inn.batting_team,
        "batting_team_name": engine.teams[inn.batting_team]["name"],
        "bowling_team_name": engine.teams[inn.bowling_team]["name"],
        "runs": inn.runs,
        "wickets": inn.wickets,
        "overs": overs_str(inn.legal_balls, engine.balls_per_over),
        "run_rate": economy(inn.runs, inn.legal_balls, engine.balls_per_over),
        "extras": extras,
        "batting": batting,
        "retired": [r["name"] for r in batting if r["status"] == "retired"],
        "did_not_bat": did_not_bat,
        "bowling": [bowler_view(engine, bw) for bw in sorted(inn.bowlers.values(), key=lambda b: b.order)],
        "fall_of_wickets": [
            {**f, "name": engine.player_name(f["player_id"])} for f in inn.fall_of_wickets
        ],
        "target": inn.target,
        "complete": inn.complete,
        "end_reason": inn.end_reason,
        "balls": [delivery_view(engine, d) for d in inn.deliveries],
    }


def match_summary(engine: MatchEngine) -> dict[str, Any]:
    team_scores = []
    for t_idx, team in enumerate(engine.teams):
        innings = [i for i in engine.innings if i.batting_team == t_idx]
        team_scores.append(
            {
                "team": t_idx,
                "name": team["name"],
                "runs": sum(i.runs for i in innings),
                "wickets": sum(i.wickets for i in innings),
                "innings": [f"{i.runs}/{i.wickets} ({overs_str(i.legal_balls, engine.balls_per_over)})" for i in innings],
            }
        )

    batting_totals: dict[str, dict[str, int]] = {}
    bowling_totals: dict[str, dict[str, int]] = {}
    for inn in engine.innings:
        for b in inn.batters.values():
            t = batting_totals.setdefault(b.player_id, {"runs": 0, "balls": 0})
            t["runs"] += b.runs
            t["balls"] += b.balls
        for bw in inn.bowlers.values():
            t = bowling_totals.setdefault(bw.player_id, {"wickets": 0, "runs": 0, "balls": 0})
            t["wickets"] += bw.wickets
            t["runs"] += bw.runs
            t["balls"] += bw.balls

    top_batsman = None
    if batting_totals:
        pid, t = max(batting_totals.items(), key=lambda kv: (kv[1]["runs"], -kv[1]["balls"]))
        top_batsman = {
            "id": pid,
            "name": engine.player_name(pid),
            "team_name": engine.teams[engine.player_team[pid]]["name"],
            **t,
            "strike_rate": strike_rate(t["runs"], t["balls"]),
        }
    top_bowler = None
    if bowling_totals:
        pid, t = max(bowling_totals.items(), key=lambda kv: (kv[1]["wickets"], -kv[1]["runs"]))
        top_bowler = {
            "id": pid,
            "name": engine.player_name(pid),
            "team_name": engine.teams[engine.player_team[pid]]["name"],
            "wickets": t["wickets"],
            "runs": t["runs"],
            "overs": overs_str(t["balls"], engine.balls_per_over),
            "economy": economy(t["runs"], t["balls"], engine.balls_per_over),
        }

    return {
        "status": engine.status,
        "result": engine.result(),
        "team_scores": team_scores,
        "top_batsman": top_batsman,
        "top_bowler": top_bowler,
    }


def live_state(engine: MatchEngine) -> dict[str, Any]:
    inn = engine.current
    current = None
    if inn is not None:
        last_over = inn.deliveries[-1].over if inn.deliveries else 0
        current = {
            "innings_number": inn.number,
            "batting_team": inn.batting_team,
            "bowling_team": inn.bowling_team,
            "batting_team_name": engine.teams[inn.batting_team]["name"],
            "bowling_team_name": engine.teams[inn.bowling_team]["name"],
            "runs": inn.runs,
            "wickets": inn.wickets,
            "overs": overs_str(inn.legal_balls, engine.balls_per_over),
            "legal_balls": inn.legal_balls,
            "total_balls": engine.total_balls,
            "run_rate": economy(inn.runs, inn.legal_balls, engine.balls_per_over),
            "extras": sum(inn.extras.values()),
            "striker": batter_view(engine, inn.batters[inn.striker]) if inn.striker else None,
            "non_striker": batter_view(engine, inn.batters[inn.non_striker]) if inn.non_striker else None,
            "bowler": bowler_view(engine, inn.bowlers[inn.bowler]) if inn.bowler else None,
            "previous_bowler": inn.previous_bowler,
            "partnership": {"runs": inn.partnership_runs, "balls": inn.partnership_balls},
            "this_over": [d.label for d in inn.deliveries if d.over == last_over],
            "recent_balls": [delivery_view(engine, d) for d in reversed(inn.deliveries[-RECENT_BALLS:])],
            "chase": chase_view(engine, inn),
            "extra_runs": {e: engine.penalty_runs(inn, e) for e in ("wide", "no_ball")},
            "in_pairing": engine.in_pairing(inn),
            "complete": inn.complete,
            "end_reason": inn.end_reason,
        }

    available = []
    bowlers = []
    if inn is not None and not inn.complete:
        for pid in engine.available_batsmen(inn):
            b = inn.batters.get(pid)
            available.append({"id": pid, "name": engine.player_name(pid), "retired": b is not None})
        for p in engine.team_players(inn.bowling_team):
            bw = inn.bowlers.get(p["id"])
            bowlers.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "overs": overs_str(bw.balls, engine.balls_per_over) if bw else "0.0",
                    "runs": bw.runs if bw else 0,
                    "wickets": bw.wickets if bw else 0,
                    "bowled_last_over": p["id"] == inn.previous_bowler,
                }
            )

    return {
        "status": engine.status,
        "overs": engine.overs,
        "pairing_overs": engine.pairing_overs,
        "next_action": engine.next_action,
        "current": current,
        "next_batting_team": engine.next_batting_team,
        "available_batsmen": available,
        "bowlers": bowlers,
        "result": engine.result(),
    }
