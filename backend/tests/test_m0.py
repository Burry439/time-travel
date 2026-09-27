from fastapi.testclient import TestClient

from app import app
import app as service


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service.store, "DB_PATH", tmp_path / "m0.sqlite3")
    return TestClient(app)


def step(http, run_id, state, x, y, request_id, running=False):
    return http.post(f"/runs/{run_id}/move", json={
        "x": x, "y": y, "expected_version": state["event_seq"], "request_id": request_id,
        "running": running,
    })


def test_seed_and_locked_wall(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    assert http.get("/health").json()["status"] == "ok"
    state = http.post("/runs", json={"mode": "normal"}).json()
    assert len(state["npcs"]) == 10
    assert {n["name"] for n in state["npcs"]} >= {"Elin", "Kade"}
    assert (state["player"]["x"], state["player"]["y"]) == (48, 68)
    assert step(http, state["run_id"], state, 48, 8, "teleport").status_code == 422
    assert http.post(f"/runs/{state['run_id']}/dev/gate", json={
        "open": True, "expected_version": 0, "request_id": "cheat",
    }).status_code == 403
    assert http.get(f"/runs/{state['run_id']}").json()["event_seq"] == 0


def test_replay_gate_entry_and_duplicate(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={"mode": "developer"}).json()
    run_id = state["run_id"]
    response = http.post(f"/runs/{run_id}/dev/gate", json={
        "open": True, "expected_version": 0, "request_id": "dev-open",
    })
    assert response.status_code == 200
    state = response.json()["state"]
    for y in range(67, 2, -1):
        response = step(http, run_id, state, 48, y, f"step-{y}")
        assert response.status_code == 200, response.text
        state = response.json()["state"]
    assert state["inside_city"]
    assert state["sim_time_ms"] == 0  # Exploration time now comes from the clock.
    assert state["tick"] == state["sim_time_ms"] // 1000
    events = http.get(f"/runs/{run_id}/events").json()
    assert [e["kind"] for e in events].count("objective_complete") == 1
    assert http.get(f"/runs/{run_id}").json() == state
    duplicate = step(http, run_id, {"event_seq": 2}, 48, 67, "step-67")
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"]
    assert duplicate.json()["state"]["player"]["y"] == 67
    assert duplicate.json()["state"]["event_seq"] == 2
    assert len(http.get(f"/runs/{run_id}/events").json()) == len(events)


def test_closed_gate_and_stale_version(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={"mode": "developer"}).json()
    run_id = state["run_id"]
    for y in range(67, 8, -1):
        response = step(http, run_id, state, 48, y, f"move-{y}")
        assert response.status_code == 200
        state = response.json()["state"]
    assert step(http, run_id, state, 48, 8, "closed").status_code == 403
    opened = http.post(f"/runs/{run_id}/dev/gate", json={
        "open": True, "expected_version": state["event_seq"], "request_id": "open",
    }).json()["state"]
    assert step(http, run_id, state, 48, 8, "stale").status_code == 409
    assert step(http, run_id, opened, 48, 8, "accepted").status_code == 200


def test_diagonal_speed_and_corner_rule(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={"mode": "developer"}).json()
    run_id = state["run_id"]
    diagonal = step(http, run_id, state, 49, 67, "diagonal")
    assert diagonal.status_code == 200
    state = diagonal.json()["state"]
    assert state["sim_time_ms"] == 0
    sprint = step(http, run_id, state, 50, 67, "sprint", running=True)
    assert sprint.status_code == 200
    state = sprint.json()["state"]
    assert state["sim_time_ms"] == 0
    assert http.get(f"/runs/{run_id}/events").json()[-1]["payload"]["running"]
    assert step(http, run_id, state, 52, 66, "jump").status_code == 422
    for x in range(49, 44, -1):
        state = step(http, run_id, state, x, 67, f"left-{x}").json()["state"]
    for y in range(66, 8, -1):
        state = step(http, run_id, state, 45, y, f"north-{y}").json()["state"]
    opened = http.post(f"/runs/{run_id}/dev/gate", json={
        "open": True, "expected_version": state["event_seq"], "request_id": "open",
    }).json()["state"]
    assert step(http, run_id, opened, 46, 8, "corner-cut").status_code == 403
