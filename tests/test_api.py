import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.storage.local import LocalJsonStorageProvider


@pytest.fixture
def client(tmp_path):
    settings = Settings(storage_provider="local", data_dir=tmp_path, delete_password="test-pass", scorer_password="scorer-test")
    with TestClient(create_app(settings)) as c:
        c.post("/api/scorer/session", json={"password": "scorer-test"})
        yield c


DELETE_HEADERS = {"X-Delete-Password": "test-pass"}

MATCH = {
    "name": "Friday Night",
    "date": "2026-10-16",
    "venue": "Arena 1",
    "settings": {"overs": 1, "balls_per_over": 6, "innings": 2},
    "teams": [
        {"name": "Alpha", "players": [{"name": "A1", "shirt": 7}, {"name": "A2"}, {"name": "A3"}]},
        {"name": "Bravo", "players": [{"name": "B1"}, {"name": "B2"}, {"name": "B3"}]},
    ],
}


def post_event(client, match_id, event, op_id=None):
    return client.post(f"/api/matches/{match_id}/events", json={"event": event, "op_id": op_id})


def test_full_match_flow(client, tmp_path):
    r = client.post("/api/matches", json=MATCH)
    assert r.status_code == 201
    view = r.json()
    mid = view["match"]["id"]
    assert view["state"]["next_action"] == "start_innings"
    assert (tmp_path / "matches" / f"{mid}.json").exists()

    r = post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    assert r.status_code == 200
    for _ in range(6):
        r = post_event(client, mid, {"type": "ball", "runs": 1})
    assert r.json()["state"]["next_action"] == "start_innings"

    post_event(client, mid, {"type": "innings_start", "striker": "t1p0", "non_striker": "t1p1", "bowler": "t0p0"})
    r = post_event(client, mid, {"type": "ball", "runs": 6, "additional": [1]})
    state = r.json()["state"]
    assert state["status"] == "completed"
    assert state["result"]["text"].startswith("Bravo won by")

    sc = client.get(f"/api/matches/{mid}/scorecard").json()
    assert len(sc["innings"]) == 2
    assert sc["summary"]["top_batsman"]["runs"] == 7

    listing = client.get("/api/matches?status=completed").json()
    assert [m["id"] for m in listing] == [mid]


def test_scorer_password_protects_live_api_but_not_scorecard(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    client.cookies.clear()

    assert client.get("/api/matches").status_code == 200
    assert client.get(f"/api/matches/{mid}/scorecard").status_code == 200
    assert client.get("/api/scorer/session").json() == {"authenticated": False}
    assert client.get(f"/api/matches/{mid}").status_code == 401
    assert client.post(f"/api/matches/{mid}/events", json={"event": {"type": "ball", "runs": 1}}).status_code == 401
    assert client.get(f"/api/matches/{mid}/export").status_code == 200
    assert client.post("/api/scorer/session", json={"password": "wrong"}).status_code == 403

    login = client.post("/api/scorer/session", json={"password": "scorer-test"})
    assert login.status_code == 200
    assert login.headers["set-cookie"].lower().find("httponly") >= 0
    assert client.get(f"/api/matches/{mid}").status_code == 200
    assert client.delete("/api/scorer/session").status_code == 204
    assert client.get(f"/api/matches/{mid}").status_code == 401


def test_pairing_boundary_retires_pair_and_survives_backup_import(client):
    match = {**MATCH, "settings": {"overs": 3, "balls_per_over": 1, "pairing_overs": 2}}
    mid = client.post("/api/matches", json=match).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    post_event(client, mid, {"type": "ball", "runs": 0})
    post_event(client, mid, {"type": "bowler", "bowler": "t1p1"})
    state = post_event(client, mid, {"type": "ball", "runs": 0}).json()["state"]
    assert state["next_action"] == "select_batsman"
    exported = client.get(f"/api/matches/{mid}/export")
    assert exported.json()["events"][-1]["auto_retire_pair"] is True
    imported = client.post("/api/matches/import", content=exported.content)
    assert imported.status_code == 201
    assert imported.json()["state"]["next_action"] == "select_batsman"


def test_invalid_event_returns_400_and_is_not_saved(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    r = post_event(client, mid, {"type": "ball", "runs": 1})
    assert r.status_code == 400
    assert client.get(f"/api/matches/{mid}").json()["state"]["can_undo"] is False


def test_duplicate_op_id_is_ignored(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    post_event(client, mid, {"type": "ball", "runs": 4}, op_id="abc")
    r = post_event(client, mid, {"type": "ball", "runs": 4}, op_id="abc")
    assert r.json()["state"]["current"]["runs"] == 4


def test_undo_endpoint(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    post_event(client, mid, {"type": "ball", "runs": 4})
    r = client.post(f"/api/matches/{mid}/undo", json={})
    assert r.json()["state"]["current"]["runs"] == 0


def test_export_import_roundtrip_and_delete(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    post_event(client, mid, {"type": "ball", "runs": 3})
    exported = client.get(f"/api/matches/{mid}/export")
    assert "attachment" in exported.headers["content-disposition"]

    r = client.post("/api/matches/import", content=exported.content)
    assert r.status_code == 201
    imported = r.json()
    assert imported["match"]["id"] != mid  # id clash gets a fresh id
    assert imported["state"]["current"]["runs"] == 3

    assert client.delete(f"/api/matches/{mid}").status_code == 403
    assert client.delete(f"/api/matches/{mid}", headers={"X-Delete-Password": "wrong"}).status_code == 403
    assert client.delete(f"/api/matches/{mid}", headers=DELETE_HEADERS).status_code == 204
    assert client.get(f"/api/matches/{mid}").status_code == 404


def test_import_rejects_inconsistent_events(client):
    doc = {**MATCH, "teams": [
        {"name": "A", "players": [{"id": "a1", "name": "A1"}, {"id": "a2", "name": "A2"}]},
        {"name": "B", "players": [{"id": "b1", "name": "B1"}, {"id": "b2", "name": "B2"}]},
    ], "events": [{"type": "ball", "runs": 1}]}
    r = client.post("/api/matches/import", content=json.dumps(doc))
    assert r.status_code == 400


def test_path_traversal_ids_rejected(client):
    assert client.get("/api/matches/..%2F..%2Fetc").status_code == 404
    assert client.delete("/api/matches/bad.id", headers=DELETE_HEADERS).status_code == 404


def test_update_details_rename_add_and_protect_used_players(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    teams = client.get(f"/api/matches/{mid}").json()["match"]["teams"]

    body = {
        "name": "Renamed",
        "date": "2026-10-17",
        "venue": "Arena 2",
        "teams": [
            {"name": "Alpha FC", "players": [*teams[0]["players"][:2], {"name": "New Guy", "shirt": 9}]},
            teams[1],
        ],
    }
    r = client.put(f"/api/matches/{mid}/details", json=body)
    assert r.status_code == 200, r.text
    match = r.json()["match"]
    assert match["name"] == "Renamed" and match["teams"][0]["name"] == "Alpha FC"
    new_ids = [p["id"] for p in match["teams"][0]["players"]]
    assert new_ids[:2] == ["t0p0", "t0p1"] and new_ids[2] not in ("t0p0", "t0p1", "t0p2")

    body["teams"][0]["players"] = match["teams"][0]["players"][1:]  # drops t0p0, who is batting
    r = client.put(f"/api/matches/{mid}/details", json=body)
    assert r.status_code == 400


def test_change_overs_event(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    r = post_event(client, mid, {"type": "set_overs", "overs": 5})
    assert r.json()["state"]["overs"] == 5


def test_cancel_retirement_restores_batsmen(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    post_event(client, mid, {"type": "ball", "runs": 1})
    post_event(client, mid, {"type": "retire", "batsman": "t0p0"})
    state = post_event(client, mid, {"type": "retire", "batsman": "t0p1"}).json()["state"]
    assert state["next_action"] == "select_batsman" and state["can_cancel_retire"]

    state = client.post(f"/api/matches/{mid}/cancel-retire", json={}).json()["state"]
    assert state["next_action"] == "ball" and not state["can_cancel_retire"]
    assert state["current"]["runs"] == 1  # the ball before the retirements is kept
    assert client.post(f"/api/matches/{mid}/cancel-retire", json={}).status_code == 400


def test_edit_earlier_ball_replays_later_balls(client):
    mid = client.post("/api/matches", json=MATCH).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    for r in (1, 2, 4):
        state = post_event(client, mid, {"type": "ball", "runs": r}).json()["state"]
    recent = state["current"]["recent_balls"]
    assert [b["label"] for b in recent] == ["4", "2", "1"]
    first = recent[-1]
    assert first["event"]["runs"] == 1

    r = client.put(
        f"/api/matches/{mid}/events/{first['event_index']}",
        json={"event": {"type": "ball", "striker": first["striker"], "runs": 3}},
    )
    assert r.status_code == 200, r.text
    current = r.json()["state"]["current"]
    assert current["runs"] == 9 and current["legal_balls"] == 3

    not_ball = client.put(f"/api/matches/{mid}/events/0", json={"event": {"type": "ball", "runs": 1}})
    assert not_ball.status_code == 400


def test_pdf_export(client):
    mid = client.post("/api/matches", json={**MATCH, "name": "Café Cup ✓"}).json()["match"]["id"]
    post_event(client, mid, {"type": "innings_start", "batting_team": 0, "striker": "t0p0", "non_striker": "t0p1", "bowler": "t1p0"})
    post_event(client, mid, {"type": "ball", "striker": "t0p0", "runs": 4})
    post_event(client, mid, {"type": "ball", "striker": "t0p0", "runs": 0, "dismissal": {"type": "caught", "fielders": ["t1p1"]}})
    r = client.get(f"/api/matches/{mid}/export.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "attachment" in r.headers["content-disposition"]


def test_local_storage_provider_roundtrip(tmp_path):
    store = LocalJsonStorageProvider(tmp_path)
    store.save_match({"id": "m1", "x": 1})
    assert store.load_match("m1") == {"id": "m1", "x": 1}
    assert [m["id"] for m in store.list_matches()] == ["m1"]
    assert store.delete_match("m1") is True
    assert store.load_match("m1") is None
    with pytest.raises(ValueError):
        store.load_match("../evil")


def test_pwa_assets_served(client):
    assert client.get("/").status_code == 200
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["service-worker-allowed"] == "/"
    assert client.get("/manifest.webmanifest").headers["content-type"].startswith("application/manifest+json")
