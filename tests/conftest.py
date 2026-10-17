import copy

import pytest


def make_match(overs=2, balls_per_over=6, innings=2, players=4, wide_runs=2, no_ball_runs=2, last_over_extra_runs=1):
    return {
        "id": "test-match",
        "name": "Test",
        "date": "2026-10-16",
        "venue": "",
        "settings": {
            "overs": overs,
            "balls_per_over": balls_per_over,
            "innings": innings,
            "wide_runs": wide_runs,
            "no_ball_runs": no_ball_runs,
            "last_over_extra_runs": last_over_extra_runs,
        },
        "teams": [
            {"name": name, "players": [{"id": f"t{t}p{i}", "name": f"{name}{i}", "shirt": None} for i in range(players)]}
            for t, name in enumerate(["Alpha", "Bravo"])
        ],
        "events": [],
    }


def start(batting=0, striker=None, non_striker=None, bowler=None):
    bowling = 1 - batting
    return {
        "type": "innings_start",
        "batting_team": batting,
        "striker": striker or f"t{batting}p0",
        "non_striker": non_striker or f"t{batting}p1",
        "bowler": bowler or f"t{bowling}p0",
    }


def ball(runs=0, **kw):
    return {"type": "ball", "runs": runs, **kw}


class Builder:
    """Accumulates events and replays them through the engine."""

    def __init__(self, **settings):
        self.match = make_match(**settings)

    def add(self, *events):
        self.match["events"].extend(events)
        return self

    def engine(self):
        from app.services.engine import MatchEngine

        return MatchEngine(copy.deepcopy(self.match))


@pytest.fixture
def builder():
    return Builder
