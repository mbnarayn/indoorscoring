"""Cricket rules engine.

A match is stored as its setup plus an ordered list of events. The full match state is rebuilt by
replaying those events, which keeps auto-save trivial and makes undo exact (see undo.py).
"""

from dataclasses import dataclass, field
from typing import Any

DISMISSAL_TYPES = ("bowled", "caught", "run_out", "stumped", "hit_wicket", "other", "retired")
BOWLER_CREDITED = frozenset({"bowled", "caught", "stumped", "hit_wicket"})
STRIKER_ONLY = frozenset({"bowled", "caught", "stumped", "hit_wicket"})
EXTRA_TYPES = ("wide", "no_ball", "bye", "leg_bye")
MAX_ADDITIONAL_COMPONENTS = 10
MAX_RUNS = 50
MIN_RUNS = -3


class MatchError(ValueError):
    """Raised when an event is not valid for the current match state."""


@dataclass
class Batter:
    player_id: str
    order: int
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    status: str = "batting"  # batting | out | retired
    dismissal: str | None = None
    pair_dismissals: list[str] = field(default_factory=list)


@dataclass
class Bowler:
    player_id: str
    order: int
    balls: int = 0
    runs: int = 0
    wickets: int = 0
    wides: int = 0
    no_balls: int = 0


@dataclass
class Delivery:
    over: int
    label: str
    total: int
    legal: bool
    event_index: int = -1
    striker: str | None = None
    non_striker: str | None = None
    bowler: str | None = None


@dataclass
class Innings:
    number: int
    batting_team: int
    bowling_team: int
    target: int | None = None
    runs: int = 0
    wickets: int = 0
    legal_balls: int = 0
    extras: dict[str, int] = field(default_factory=lambda: {e: 0 for e in EXTRA_TYPES})
    batters: dict[str, Batter] = field(default_factory=dict)
    bowlers: dict[str, Bowler] = field(default_factory=dict)
    striker: str | None = None
    non_striker: str | None = None
    bowler: str | None = None
    previous_bowler: str | None = None
    partnership_runs: int = 0
    partnership_balls: int = 0
    fall_of_wickets: list[dict[str, Any]] = field(default_factory=list)
    deliveries: list[Delivery] = field(default_factory=list)
    complete: bool = False
    end_reason: str | None = None

    @property
    def has_vacancy(self) -> bool:
        return self.striker is None or self.non_striker is None

    def swap_strike(self) -> None:
        self.striker, self.non_striker = self.non_striker, self.striker


def _int(value: Any, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MatchError(f"{name} must be a whole number between {low} and {high}")
    return value


class MatchEngine:
    def __init__(self, match: dict[str, Any]):
        settings = match["settings"]
        self.overs: int = settings["overs"]
        self.balls_per_over: int = settings["balls_per_over"]
        self.num_innings: int = settings["innings"]
        self.wide_runs: int = settings.get("wide_runs", 2)
        self.no_ball_runs: int = settings.get("no_ball_runs", 2)
        self.last_over_extra_runs: int = settings.get("last_over_extra_runs", 1)
        self.pairing_overs: int = settings.get("pairing_overs", 0)
        self.teams: list[dict[str, Any]] = match["teams"]
        self.player_team: dict[str, int] = {}
        self.player_info: dict[str, dict[str, Any]] = {}
        for t_idx, team in enumerate(self.teams):
            for p in team["players"]:
                self.player_team[p["id"]] = t_idx
                self.player_info[p["id"]] = p
        self.innings: list[Innings] = []
        for idx, event in enumerate(match.get("events", [])):
            self._event_index = idx
            try:
                self.apply(event)
            except MatchError as exc:
                raise MatchError(f"Event {idx + 1}: {exc}") from exc

    # ---- derived properties -------------------------------------------------

    @property
    def total_balls(self) -> int:
        return self.overs * self.balls_per_over

    @property
    def current(self) -> Innings | None:
        return self.innings[-1] if self.innings else None

    @property
    def is_complete(self) -> bool:
        return len(self.innings) == self.num_innings and self.innings[-1].complete

    @property
    def status(self) -> str:
        if not self.innings:
            return "setup"
        return "completed" if self.is_complete else "in_progress"

    @property
    def next_batting_team(self) -> int | None:
        if not self.innings or self.is_complete:
            return None
        return 1 - self.innings[-1].batting_team

    @property
    def next_action(self) -> str:
        if self.is_complete:
            return "match_complete"
        inn = self.current
        if inn is None or inn.complete:
            return "start_innings"
        if inn.has_vacancy:
            return "select_batsman"
        if inn.bowler is None:
            return "select_bowler"
        return "ball"

    def player_name(self, player_id: str | None) -> str:
        if player_id is None:
            return ""
        return self.player_info.get(player_id, {}).get("name", player_id)

    def team_players(self, team: int) -> list[dict[str, Any]]:
        return self.teams[team]["players"]

    def team_total(self, team: int) -> int:
        return sum(i.runs for i in self.innings if i.batting_team == team)

    def available_batsmen(self, inn: Innings) -> list[str]:
        """Players who may come in: those yet to bat plus retired (not out) batsmen."""
        at_crease = {inn.striker, inn.non_striker}
        result = []
        for p in self.team_players(inn.batting_team):
            pid = p["id"]
            if pid in at_crease:
                continue
            batter = inn.batters.get(pid)
            if batter is None or batter.status == "retired":
                result.append(pid)
        return result

    # ---- event handling -----------------------------------------------------

    def apply(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise MatchError("Event must be an object")
        handler = {
            "innings_start": self._innings_start,
            "bowler": self._bowler,
            "ball": self._ball,
            "new_batsman": self._new_batsman,
            "retire": self._retire,
            "end_innings": self._end_innings,
            "set_overs": self._set_overs,
            "set_pairing_overs": self._set_pairing_overs,
        }.get(event.get("type"))
        if handler is None:
            raise MatchError(f"Unknown event type {event.get('type')!r}")
        handler(event)

    def _active(self) -> Innings:
        inn = self.current
        if inn is None or inn.complete:
            raise MatchError("No innings in progress")
        return inn

    def _require_team_player(self, player_id: Any, team: int, role: str) -> str:
        if not isinstance(player_id, str) or self.player_team.get(player_id) != team:
            raise MatchError(f"{role} must be a player from {self.teams[team]['name']}")
        return player_id

    def _innings_start(self, ev: dict[str, Any]) -> None:
        if self.is_complete:
            raise MatchError("Match is already complete")
        if self.current is not None and not self.current.complete:
            raise MatchError("Current innings is still in progress")
        if len(self.innings) >= self.num_innings:
            raise MatchError("All innings have been played")

        batting = ev.get("batting_team")
        expected = self.next_batting_team
        if expected is None:
            if batting not in (0, 1) or isinstance(batting, bool):
                raise MatchError("Choose the batting team")
        else:
            if batting is None:
                batting = expected
            elif batting != expected:
                raise MatchError(f"{self.teams[expected]['name']} must bat in this innings")
        bowling = 1 - batting

        striker = self._require_team_player(ev.get("striker"), batting, "Striker")
        non_striker = self._require_team_player(ev.get("non_striker"), batting, "Non-striker")
        if striker == non_striker:
            raise MatchError("Opening batsmen must be different players")
        bowler = self._require_team_player(ev.get("bowler"), bowling, "Bowler")

        number = len(self.innings) + 1
        inn = Innings(number=number, batting_team=batting, bowling_team=bowling)
        if number == self.num_innings and self.num_innings >= 2:
            inn.target = self.team_total(bowling) - self.team_total(batting) + 1
        inn.batters[striker] = Batter(striker, order=1)
        inn.batters[non_striker] = Batter(non_striker, order=2)
        inn.striker, inn.non_striker = striker, non_striker
        inn.bowlers[bowler] = Bowler(bowler, order=1)
        inn.bowler = bowler
        self.innings.append(inn)
        if inn.target is not None and inn.target <= 0:
            inn.complete, inn.end_reason = True, "target_reached"

    def _bowler(self, ev: dict[str, Any]) -> None:
        inn = self._active()
        pid = self._require_team_player(ev.get("bowler"), inn.bowling_team, "Bowler")
        if pid not in inn.bowlers:
            inn.bowlers[pid] = Bowler(pid, order=len(inn.bowlers) + 1)
        inn.bowler = pid

    def _new_batsman(self, ev: dict[str, Any]) -> None:
        inn = self._active()
        if not inn.has_vacancy:
            raise MatchError("Both batsmen are already at the crease")
        pid = self._require_team_player(ev.get("batsman"), inn.batting_team, "Batsman")
        if pid not in self.available_batsmen(inn):
            raise MatchError(f"{self.player_name(pid)} is not available to bat")
        batter = inn.batters.get(pid)
        if batter is None:
            inn.batters[pid] = Batter(pid, order=len(inn.batters) + 1)
        else:  # retired batsman returning
            batter.status, batter.dismissal = "batting", None
        if inn.striker is None:
            inn.striker = pid
        else:
            inn.non_striker = pid
        inn.partnership_runs = inn.partnership_balls = 0

    def _retire(self, ev: dict[str, Any]) -> None:
        inn = self._active()
        pid = ev.get("batsman")
        if pid is None or pid not in (inn.striker, inn.non_striker):
            raise MatchError("Only a batsman at the crease can retire")
        self._remove_batter(inn, pid, "retired")

    def in_pairing(self, inn: Innings) -> bool:
        return inn.legal_balls // self.balls_per_over < self.pairing_overs

    def _set_pairing_overs(self, ev: dict[str, Any]) -> None:
        if self.is_complete:
            raise MatchError("Match is already complete")
        self.pairing_overs = _int(ev.get("pairing_overs"), 0, 50, "Pairing overs")

    def _set_overs(self, ev: dict[str, Any]) -> None:
        if self.is_complete:
            raise MatchError("Match is already complete")
        overs = _int(ev.get("overs"), 1, 50, "Overs")
        inn = self.current
        active = inn is not None and not inn.complete
        if active and overs * self.balls_per_over < inn.legal_balls:
            raise MatchError(
                f"{overs_str(inn.legal_balls, self.balls_per_over)} overs have already been bowled this innings"
            )
        self.overs = overs
        if active:
            self._check_innings_end(inn)

    def _end_innings(self, ev: dict[str, Any]) -> None:
        inn = self._active()
        inn.complete, inn.end_reason = True, "declared"

    def in_last_over(self, inn: Innings) -> bool:
        return inn.legal_balls // self.balls_per_over == self.overs - 1

    def penalty_runs(self, inn: Innings, extra: str) -> int:
        if self.in_last_over(inn):
            return self.last_over_extra_runs
        return self.wide_runs if extra == "wide" else self.no_ball_runs

    def _ball(self, ev: dict[str, Any]) -> None:
        inn = self._active()
        if inn.has_vacancy:
            raise MatchError("Select the incoming batsman first")
        if inn.bowler is None:
            raise MatchError("Select the bowler for this over first")

        striker = ev.get("striker") or inn.striker
        if striker not in (inn.striker, inn.non_striker):
            raise MatchError("Striker must be one of the batsmen at the crease")
        if striker != inn.striker:
            inn.swap_strike()
        facing, other_end = inn.striker, inn.non_striker

        runs = _int(ev.get("runs", 0), MIN_RUNS, MAX_RUNS, "Runs")
        additional = ev.get("additional") or []
        if not isinstance(additional, list) or len(additional) > MAX_ADDITIONAL_COMPONENTS:
            raise MatchError("Additional runs must be a short list")
        additional = [_int(a, 1, 6, "Additional runs") for a in additional]
        extra = ev.get("extra")
        if extra is not None and extra not in EXTRA_TYPES:
            raise MatchError(f"Unknown extra type {extra!r}")

        dismissal = ev.get("dismissal")
        dtype = out_id = None
        if dismissal is not None:
            if not isinstance(dismissal, dict) or dismissal.get("type") not in DISMISSAL_TYPES:
                raise MatchError("Invalid dismissal")
            dtype = dismissal["type"]
            out_id = dismissal.get("batsman") or inn.striker
            if out_id not in (inn.striker, inn.non_striker):
                raise MatchError("Dismissed batsman must be at the crease")
            if dtype in STRIKER_ONLY and out_id != inn.striker:
                raise MatchError(f"Only the striker can be out {dtype.replace('_', ' ')}")
            if extra in ("wide", "no_ball") and dtype in STRIKER_ONLY and not (
                extra == "wide" and dtype in {"hit_wicket", "stumped"}
            ):
                raise MatchError(f"Batsman cannot be out {dtype.replace('_', ' ')} off a {extra.replace('_', ' ')}")
            fielders = dismissal.get("fielders") or []
            max_fielders = {"caught": 1, "run_out": 2, "stumped": 1}.get(dtype, 0)
            if not isinstance(fielders, list) or len(fielders) > max_fielders or len(set(fielders)) != len(fielders):
                raise MatchError(f"Too many fielders for {dtype.replace('_', ' ')}")
            for f in fielders:
                self._require_team_player(f, inn.bowling_team, "Fielder")

        bat_runs = runs + sum(additional)
        pairing = self.in_pairing(inn)
        over_index = inn.legal_balls // self.balls_per_over
        last_over = self.in_last_over(inn)
        is_penalty_extra = extra in ("wide", "no_ball")
        penalty = self.penalty_runs(inn, extra) if is_penalty_extra else 0
        # Indoor rule: wides/no balls count as deliveries, except in the last over where they are re-bowled.
        legal = not (is_penalty_extra and last_over)
        total = bat_runs + penalty

        batter = inn.batters[inn.striker]
        bowler = inn.bowlers[inn.bowler]
        if extra in (None, "no_ball"):
            batter.runs += bat_runs
            if runs == 4:
                batter.fours += 1
            elif runs == 6:
                batter.sixes += 1
        if extra != "wide" or legal:
            batter.balls += 1

        if extra == "wide":
            inn.extras["wide"] += total
            bowler.wides += 1
        elif extra == "no_ball":
            inn.extras["no_ball"] += penalty
            bowler.no_balls += 1
        elif extra in ("bye", "leg_bye"):
            inn.extras[extra] += bat_runs
        # Negative (penalty) runs come off the batting side only; they never reduce the bowler's figures.
        uncharged = bat_runs if extra in ("bye", "leg_bye") or bat_runs < 0 else 0
        bowler.runs += total - uncharged

        inn.runs += total
        inn.partnership_runs += total
        if extra != "wide" or legal:
            inn.partnership_balls += 1
        if legal:
            inn.legal_balls += 1
            bowler.balls += 1

        if dtype is not None:
            self._remove_batter(
                inn, out_id, dtype, bowler_id=inn.bowler, fielders=fielders, stays=pairing and dtype != "retired"
            )

        inn.deliveries.append(
            Delivery(
                over_index,
                _label(runs, additional, extra, dtype),
                total,
                legal,
                event_index=getattr(self, "_event_index", -1),
                striker=facing,
                non_striker=other_end,
                bowler=bowler.player_id,
            )
        )

        if bat_runs > 0 and bat_runs % 2 == 1:
            inn.swap_strike()
        if legal and inn.legal_balls % self.balls_per_over == 0:
            inn.swap_strike()
            inn.previous_bowler, inn.bowler = inn.bowler, None

        self._check_innings_end(inn)

        if (
            ev.get("auto_retire_pair", False)
            and not inn.complete
            and pairing
            and legal
            and inn.legal_balls % (2 * self.balls_per_over) == 0
        ):
            for player_id in (inn.striker, inn.non_striker):
                if player_id is not None:
                    self._remove_batter(inn, player_id, "retired")

    def _remove_batter(
        self,
        inn: Innings,
        pid: str,
        dtype: str,
        bowler_id: str | None = None,
        fielders: list[str] | None = None,
        stays: bool = False,
    ) -> None:
        """Record a dismissal. With `stays` (pairing overs) the wicket counts but the batsman bats on."""
        batter = inn.batters[pid]
        if dtype == "retired":
            batter.status, batter.dismissal = "retired", "retired"
        else:
            description = _describe_dismissal(
                dtype, self.player_name(bowler_id), [self.player_name(f) for f in fielders or []], bowler_id in (fielders or [])
            )
            if stays:
                batter.pair_dismissals.append(description)
            else:
                batter.status, batter.dismissal = "out", description
            inn.wickets += 1
            if dtype in BOWLER_CREDITED and bowler_id:
                inn.bowlers[bowler_id].wickets += 1
            inn.fall_of_wickets.append(
                {
                    "wicket": inn.wickets,
                    "runs": inn.runs,
                    "overs": overs_str(inn.legal_balls, self.balls_per_over),
                    "player_id": pid,
                }
            )
        if stays:
            return
        if inn.striker == pid:
            inn.striker = None
        else:
            inn.non_striker = None

    def _check_innings_end(self, inn: Innings) -> None:
        if inn.target is not None and inn.runs >= inn.target:
            inn.complete, inn.end_reason = True, "target_reached"
        elif inn.legal_balls >= self.total_balls:
            inn.complete, inn.end_reason = True, "overs_complete"
        elif inn.has_vacancy and not self.available_batsmen(inn):
            inn.complete, inn.end_reason = True, "all_out"

    # ---- result -------------------------------------------------------------

    def result(self) -> dict[str, Any] | None:
        if not self.is_complete:
            return None
        teams_batted = {i.batting_team for i in self.innings}
        if teams_batted != {0, 1}:
            return {"winner": None, "margin": None, "text": "No result"}
        totals = [self.team_total(0), self.team_total(1)]
        if totals[0] == totals[1]:
            return {"winner": None, "margin": None, "text": "Match tied"}
        winner = 0 if totals[0] > totals[1] else 1
        last = self.innings[-1]
        if winner == last.batting_team:
            wickets_left = max(0, len(self.team_players(winner)) - 1 - last.wickets)
            balls_left = self.total_balls - last.legal_balls
            margin = f"{wickets_left} wicket{'s' if wickets_left != 1 else ''}"
            if balls_left > 0:
                margin += f" ({balls_left} ball{'s' if balls_left != 1 else ''} remaining)"
        else:
            diff = totals[winner] - totals[1 - winner]
            margin = f"{diff} run{'s' if diff != 1 else ''}"
        name = self.teams[winner]["name"]
        return {"winner": winner, "winner_name": name, "margin": margin, "text": f"{name} won by {margin}"}


def overs_str(balls: int, balls_per_over: int) -> str:
    return f"{balls // balls_per_over}.{balls % balls_per_over}"


def _describe_dismissal(dtype: str, bowler_name: str, fielder_names: list[str], caught_by_bowler: bool) -> str:
    if dtype == "caught" and fielder_names:
        return f"c & b {bowler_name}" if caught_by_bowler else f"c {fielder_names[0]} b {bowler_name}"
    if dtype == "run_out" and fielder_names:
        return f"run out ({' / '.join(fielder_names)})"
    if dtype == "stumped" and fielder_names:
        return f"st {fielder_names[0]} b {bowler_name}"
    return {
        "bowled": f"b {bowler_name}",
        "caught": f"caught b {bowler_name}",
        "stumped": f"stumped b {bowler_name}",
        "hit_wicket": f"hit wicket b {bowler_name}",
        "run_out": "run out",
        "other": "out (other)",
    }[dtype]


def _label(runs: int, additional: list[int], extra: str | None, dtype: str | None) -> str:
    bat = str(runs) + "".join(f"+{a}" for a in additional)
    if extra:
        prefix = {"wide": "Wd", "no_ball": "Nb", "bye": "B", "leg_bye": "Lb"}[extra]
        label = prefix if bat == "0" else f"{prefix}{bat}"
    else:
        label = "\u2022" if bat == "0" else bat
    if dtype == "retired":
        label += " R"
    elif dtype:
        label = "W" if label == "\u2022" else f"{label} W"
    return label
