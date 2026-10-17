"""Application service: coordinates the match engine with the storage provider."""

import datetime as dt
import secrets
import threading
from typing import Any

from app.services.engine import MatchEngine, MatchError
from app.services.stats import innings_scorecard, live_state, match_summary
from app.services.undo import cancel_retirements, trailing_retirements, undo_last_ball
from app.storage.base import StorageProvider, is_valid_match_id

SCHEMA_VERSION = 1
MAX_RECENT_OPS = 200


class MatchNotFound(LookupError):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _new_match_id(date: str) -> str:
    return f"{date.replace('-', '')}-{secrets.token_hex(4)}"


class MatchService:
    def __init__(self, storage: StorageProvider):
        self._storage = storage
        # Serialises read-modify-write cycles so concurrent requests cannot lose deliveries.
        self._lock = threading.RLock()

    # ---- queries ------------------------------------------------------------

    def _load(self, match_id: str) -> dict[str, Any]:
        if not is_valid_match_id(match_id):
            raise MatchNotFound(match_id)
        doc = self._storage.load_match(match_id)
        if doc is None:
            raise MatchNotFound(match_id)
        return doc

    def get_view(self, match_id: str) -> dict[str, Any]:
        return self._view(self._load(match_id))

    def list_matches(self, status: str | None = None) -> list[dict[str, Any]]:
        items = []
        for doc in self._storage.list_matches():
            summary = doc.get("summary") or {}
            if status and doc.get("status") != status:
                continue
            items.append(
                {
                    "id": doc["id"],
                    "name": doc.get("name"),
                    "date": doc.get("date"),
                    "venue": doc.get("venue"),
                    "status": doc.get("status"),
                    "teams": [t["name"] for t in doc.get("teams", [])],
                    "headline": summary.get("headline", ""),
                    "updated_at": doc.get("updated_at"),
                }
            )
        items.sort(key=lambda m: m.get("updated_at") or "", reverse=True)
        return items

    def scorecard(self, match_id: str) -> dict[str, Any]:
        doc = self._load(match_id)
        engine = MatchEngine(doc)
        innings = [innings_scorecard(engine, inn) for inn in engine.innings]
        events = doc.get("events", [])
        for inn in innings:
            for ball in inn["balls"]:
                _attach_event(ball, events)
        return {
            "match": self._public(doc),
            "innings": innings,
            "summary": match_summary(engine),
        }

    def export_match(self, match_id: str) -> dict[str, Any]:
        doc = self._load(match_id)
        return {k: v for k, v in doc.items() if k not in ("summary", "recent_ops")}

    # ---- commands -----------------------------------------------------------

    def create_match(self, data: dict[str, Any]) -> dict[str, Any]:
        date = str(data["date"])
        teams = [
            {
                "name": team["name"],
                "players": [
                    {"id": f"t{t_idx}p{p_idx}", "name": p["name"], "shirt": p.get("shirt")}
                    for p_idx, p in enumerate(team["players"])
                ],
            }
            for t_idx, team in enumerate(data["teams"])
        ]
        now = _now()
        doc = {
            "id": _new_match_id(date),
            "schema_version": SCHEMA_VERSION,
            "name": data["name"],
            "date": date,
            "venue": data.get("venue", ""),
            "settings": dict(data["settings"]),
            "teams": teams,
            "events": [],
            "created_at": now,
        }
        with self._lock:
            return self._persist(doc)

    def add_event(self, match_id: str, event: dict[str, Any], op_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            doc = self._load(match_id)
            if op_id and op_id in doc.get("recent_ops", []):
                return self._view(doc)  # duplicate submission (e.g. offline replay retry)
            event = {**event, "ts": _now()}
            doc["events"] = [*doc.get("events", []), event]
            self._remember_op(doc, op_id)
            return self._persist(doc)

    def undo(self, match_id: str, op_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            doc = self._load(match_id)
            if op_id and op_id in doc.get("recent_ops", []):
                return self._view(doc)
            doc["events"] = undo_last_ball(doc.get("events", []))
            self._remember_op(doc, op_id)
            return self._persist(doc)

    def cancel_retirement(self, match_id: str, op_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            doc = self._load(match_id)
            if op_id and op_id in doc.get("recent_ops", []):
                return self._view(doc)
            doc["events"] = cancel_retirements(doc.get("events", []))
            self._remember_op(doc, op_id)
            return self._persist(doc)

    def edit_ball(self, match_id: str, index: int, event: dict[str, Any], op_id: str | None = None) -> dict[str, Any]:
        """Replace an earlier delivery and replay; rejected if later play no longer fits."""
        with self._lock:
            doc = self._load(match_id)
            if op_id and op_id in doc.get("recent_ops", []):
                return self._view(doc)
            events = doc.get("events", [])
            if not 0 <= index < len(events) or events[index].get("type") != "ball":
                raise MatchError("That ball can no longer be edited")
            replaced = {**event, "ts": events[index].get("ts") or _now()}
            doc["events"] = [*events[:index], replaced, *events[index + 1 :]]
            try:
                MatchEngine(doc)
            except MatchError as exc:
                raise MatchError(f"This change conflicts with later play ({exc}). Undo back to that ball instead.") from exc
            self._remember_op(doc, op_id)
            return self._persist(doc)

    def update_details(self, match_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Edit match name/date/venue and team rosters; players who have taken part cannot be removed."""
        with self._lock:
            doc = self._load(match_id)
            used = _referenced_players(doc.get("events", []))
            all_ids = {p["id"] for t in doc["teams"] for p in t["players"]}
            teams = []
            for t_idx, (old, new) in enumerate(zip(doc["teams"], data["teams"])):
                old_players = {p["id"]: p for p in old["players"]}
                players, seen = [], set()
                for p in new["players"]:
                    pid = p.get("id")
                    if pid is None:
                        n = len(all_ids)
                        while f"t{t_idx}p{n}" in all_ids:
                            n += 1
                        pid = f"t{t_idx}p{n}"
                        all_ids.add(pid)
                    elif pid not in old_players or pid in seen:
                        raise MatchError(f"Unknown or duplicate player id {pid!r}")
                    seen.add(pid)
                    players.append({"id": pid, "name": p["name"], "shirt": p.get("shirt")})
                for pid in set(old_players) - seen:
                    if pid in used:
                        raise MatchError(f"{old_players[pid]['name']} has already played and cannot be removed")
                teams.append({"name": new["name"], "players": players})
            doc.update(name=data["name"], date=str(data["date"]), venue=data.get("venue", ""), teams=teams)
            return self._persist(doc)

    def delete_match(self, match_id: str) -> None:
        if not is_valid_match_id(match_id):
            raise MatchNotFound(match_id)
        with self._lock:
            if not self._storage.delete_match(match_id):
                raise MatchNotFound(match_id)

    def import_match(self, doc: dict[str, Any]) -> dict[str, Any]:
        """`doc` must already be schema-validated; events are replayed to verify they are consistent."""
        with self._lock:
            match_id = doc.get("id")
            if not match_id or not is_valid_match_id(match_id) or self._storage.load_match(match_id) is not None:
                match_id = _new_match_id(str(doc["date"]))
            imported = {
                "id": match_id,
                "schema_version": SCHEMA_VERSION,
                "name": doc["name"],
                "date": str(doc["date"]),
                "venue": doc.get("venue", ""),
                "settings": dict(doc["settings"]),
                "teams": doc["teams"],
                "events": doc.get("events", []),
                "created_at": doc.get("created_at") or _now(),
            }
            return self._persist(imported)

    # ---- helpers ------------------------------------------------------------

    @staticmethod
    def _remember_op(doc: dict[str, Any], op_id: str | None) -> None:
        if op_id:
            doc["recent_ops"] = [*doc.get("recent_ops", []), op_id][-MAX_RECENT_OPS:]

    def _persist(self, doc: dict[str, Any]) -> dict[str, Any]:
        engine = MatchEngine(doc)  # raises MatchError if the new event list is invalid
        doc["status"] = engine.status
        doc["updated_at"] = _now()
        doc["summary"] = {"headline": _headline(engine)}
        self._storage.save_match(doc)
        return self._view(doc, engine)

    @staticmethod
    def _public(doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": doc["id"],
            "name": doc["name"],
            "date": doc["date"],
            "venue": doc.get("venue", ""),
            "settings": doc["settings"],
            "teams": doc["teams"],
            "status": doc.get("status"),
            "updated_at": doc.get("updated_at"),
        }

    def _view(self, doc: dict[str, Any], engine: MatchEngine | None = None) -> dict[str, Any]:
        engine = engine or MatchEngine(doc)
        state = live_state(engine)
        state["can_undo"] = bool(doc.get("events"))
        state["can_cancel_retire"] = trailing_retirements(doc.get("events", [])) > 0
        events = doc.get("events", [])
        for rb in (state.get("current") or {}).get("recent_balls", []):
            _attach_event(rb, events)
        return {"match": self._public(doc), "state": state}


def _attach_event(ball: dict[str, Any], events: list[dict[str, Any]]) -> None:
    ev = events[ball["event_index"]] if 0 <= ball["event_index"] < len(events) else {}
    ball["event"] = {k: v for k, v in ev.items() if k != "ts"}


def _referenced_players(events: list[dict[str, Any]]) -> set[str]:
    ids = set()
    for e in events:
        for key in ("striker", "non_striker", "bowler", "batsman"):
            if e.get(key):
                ids.add(e[key])
        if isinstance(e.get("dismissal"), dict):
            if e["dismissal"].get("batsman"):
                ids.add(e["dismissal"]["batsman"])
            ids.update(e["dismissal"].get("fielders") or [])
    return ids


def _headline(engine: MatchEngine) -> str:
    result = engine.result()
    if result:
        return result["text"]
    inn = engine.current
    if inn is None:
        return "Not started"
    team = engine.teams[inn.batting_team]["name"]
    overs = f"{inn.legal_balls // engine.balls_per_over}.{inn.legal_balls % engine.balls_per_over}"
    return f"{team} {inn.runs}/{inn.wickets} ({overs} ov)"


__all__ = ["MatchService", "MatchNotFound", "MatchError"]
