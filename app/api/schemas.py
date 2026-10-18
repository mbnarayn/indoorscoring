import datetime as dt
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
PlayerId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
OpId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchSettings(_Strict):
    overs: int = Field(16, ge=1, le=50)
    balls_per_over: int = Field(6, ge=1, le=12)
    innings: int = Field(2, ge=1, le=4)
    wide_runs: int = Field(2, ge=0, le=10)
    no_ball_runs: int = Field(2, ge=0, le=10)
    last_over_extra_runs: int = Field(1, ge=0, le=10)
    pairing_overs: int = Field(0, ge=0, le=50)


class PlayerIn(_Strict):
    name: Name
    shirt: int | None = Field(None, ge=0, le=999)


class TeamIn(_Strict):
    name: Name
    players: list[PlayerIn] = Field(min_length=2, max_length=20)


class MatchCreate(_Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    date: dt.date
    venue: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    settings: MatchSettings = MatchSettings()
    teams: list[TeamIn] = Field(min_length=2, max_length=2)


class ScorerLogin(_Strict):
    password: str


# ---- events -------------------------------------------------------------------


class Dismissal(_Strict):
    type: Literal["bowled", "caught", "run_out", "stumped", "hit_wicket", "other", "retired"]
    batsman: PlayerId | None = None
    fielders: list[PlayerId] = Field(default_factory=list, max_length=2)


class BallEvent(_Strict):
    type: Literal["ball"]
    auto_retire_pair: bool = False
    striker: PlayerId | None = None
    runs: int = Field(0, ge=-3, le=50)
    additional: list[Annotated[int, Field(ge=1, le=6)]] = Field(default_factory=list, max_length=10)
    extra: Literal["wide", "no_ball", "bye", "leg_bye"] | None = None
    dismissal: Dismissal | None = None


class BowlerEvent(_Strict):
    type: Literal["bowler"]
    bowler: PlayerId


class NewBatsmanEvent(_Strict):
    type: Literal["new_batsman"]
    batsman: PlayerId


class RetireEvent(_Strict):
    type: Literal["retire"]
    batsman: PlayerId


class InningsStartEvent(_Strict):
    type: Literal["innings_start"]
    batting_team: int | None = Field(None, ge=0, le=1)
    striker: PlayerId
    non_striker: PlayerId
    bowler: PlayerId


class EndInningsEvent(_Strict):
    type: Literal["end_innings"]


class SetOversEvent(_Strict):
    type: Literal["set_overs"]
    overs: int = Field(ge=1, le=50)


class SetPairingOversEvent(_Strict):
    type: Literal["set_pairing_overs"]
    pairing_overs: int = Field(ge=0, le=50)


Event = Annotated[
    Union[
        BallEvent,
        BowlerEvent,
        NewBatsmanEvent,
        RetireEvent,
        InningsStartEvent,
        EndInningsEvent,
        SetOversEvent,
        SetPairingOversEvent,
    ],
    Field(discriminator="type"),
]


_EVENT_ADAPTER: TypeAdapter = TypeAdapter(Event)


class EventRequest(_Strict):
    op_id: OpId | None = None
    event: Event


class UndoRequest(_Strict):
    op_id: OpId | None = None


class EditBallRequest(_Strict):
    op_id: OpId | None = None
    event: BallEvent


class PlayerEdit(_Strict):
    id: PlayerId | None = None
    name: Name
    shirt: int | None = Field(None, ge=0, le=999)


class TeamEdit(_Strict):
    name: Name
    players: list[PlayerEdit] = Field(min_length=2, max_length=20)


class MatchDetailsUpdate(_Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    date: dt.date
    venue: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    teams: list[TeamEdit] = Field(min_length=2, max_length=2)


# ---- stored / imported document -----------------------------------------------


class PlayerDoc(PlayerIn):
    id: PlayerId


class TeamDoc(_Strict):
    name: Name
    players: list[PlayerDoc] = Field(min_length=2, max_length=20)


class MatchDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")] | None = None
    schema_version: int = 1
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    date: dt.date
    venue: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    settings: MatchSettings
    teams: list[TeamDoc] = Field(min_length=2, max_length=2)
    events: list[dict] = Field(default_factory=list, max_length=5000)
    created_at: str | None = None

    @model_validator(mode="after")
    def _check(self):
        ids = [p.id for t in self.teams for p in t.players]
        if len(ids) != len(set(ids)):
            raise ValueError("Player ids must be unique")
        cleaned = []
        for raw in self.events:
            body = {k: v for k, v in raw.items() if k != "ts"}
            ev = _EVENT_ADAPTER.validate_python(body).model_dump(exclude_none=True)
            if raw.get("ts"):
                ev["ts"] = str(raw["ts"])[:40]
            cleaned.append(ev)
        self.events = cleaned
        return self
