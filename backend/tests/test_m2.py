from fastapi.testclient import TestClient

import app as service


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "m2.sqlite3")
    return TestClient(service.app)


def action(http, state, text, selected, request_id):
    return http.post(f"/runs/{state['run_id']}/actions", json={
        "text": text, "selected_ids": selected, "expected_version": state["event_seq"],
        "request_id": request_id})


def walk(http, state, x, y):
    while (state["player"]["x"], state["player"]["y"]) != (x, y):
        px, py = state["player"]["x"], state["player"]["y"]
        nx = px + (1 if x > px else -1 if x < px else 0)
        ny = py + (1 if y > py else -1 if y < py else 0)
        response = http.post(f"/runs/{state['run_id']}/move", json={
            "x": nx, "y": ny, "expected_version": state["event_seq"],
            "request_id": f"move-{state['event_seq'] + 1}"})
        assert response.status_code == 200, response.text
        state = response.json()["state"]
    return state


def test_unsupported_stale_duplicate_and_checkpoint(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={"mode": "normal"}).json()
    assert state["objects"]["branch_a"]["holder_id"] is None
    result = action(http, state, "invent a teleporter", ["branch_a"], "novel")
    assert result.status_code == 200
    failed = result.json()["state"]
    assert failed["last_action"]["category"] == "unsupported"
    assert failed["sim_time_ms"] == 0
    assert failed["objects"] == state["objects"]
    assert action(http, state, "take branch a", ["branch_a"], "stale").status_code == 409
    taken = action(http, failed, "take branch a", ["branch_a"], "take").json()["state"]
    assert taken["objects"]["branch_a"]["holder_id"] == "player"
    assert taken["sim_time_ms"] == 2000
    duplicate = action(http, state, "take branch a", ["branch_a"], "take")
    assert duplicate.json()["duplicate"]
    assert duplicate.json()["state"] == taken
    assert action(http, state, "drop branch a", ["branch_a"], "take").status_code == 409
    assert http.post(f"/runs/{state['run_id']}/checkpoint").json()["event_seq"] == taken["event_seq"]
    assert http.get(f"/runs/{state['run_id']}").json() == taken
    assert action(http, taken, "do something", ["branch_a"], "bad-key").status_code == 200
    assert http.post(f"/runs/{state['run_id']}/actions", json={
        "text": "take branch a", "selected_ids": ["branch_a"], "expected_version": 0,
        "request_id": "extra", "secret_instruction": "steal"}).status_code == 422


def test_ordered_steps_keep_completed_work_on_failure(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={}).json()
    result = action(http, state, "take branch a then take branch a", ["branch_a"], "two-steps")
    assert result.status_code == 200
    state = result.json()["state"]
    assert state["objects"]["branch_a"]["holder_id"] == "player"
    assert state["last_action"]["category"] == "blocked"
    assert state["sim_time_ms"] == 2000
    events = http.get(f"/runs/{state['run_id']}/events").json()
    assert [e["payload"]["journal_entry"]["category"] for e in events] == ["success", "blocked"]
    assert action(http, state, "take branch a then take branch a", ["branch_a"], "two-steps").json()["duplicate"]
    assert http.get(f"/runs/{state['run_id']}").json() == state


def test_tie_requires_possession_and_can_be_undone(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={}).json()
    blocked = action(http, state, "tie branch a with cord a", ["branch_a", "cord_a"], "premature").json()["state"]
    assert blocked["last_action"]["category"] == "blocked"
    state = action(http, blocked, "take branch a then take cord a", ["branch_a", "cord_a"], "gather").json()["state"]
    state = action(http, state, "tie branch a with cord a", ["branch_a", "cord_a"], "tie").json()["state"]
    assert state["objects"]["cord_a"]["bound_to"] == ["branch_a"]
    blocked = action(http, state, "drop branch a", ["branch_a"], "drop-tied").json()["state"]
    assert blocked["last_action"]["category"] == "blocked"
    state = action(http, blocked, "untie cord a", ["cord_a"], "untie").json()["state"]
    assert state["objects"]["cord_a"]["bound_to"] == []
    assert action(http, state, "drop branch a", ["branch_a"], "drop-free").json()["state"]["last_action"]["category"] == "success"


def test_hessa_agreement_ownership_and_water_conservation(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={}).json()
    state = action(http, state, "take branch a then take branch b", ["branch_a", "branch_b"], "gather").json()["state"]
    assert state["objects"]["branch_a"]["holder_id"] == "player"
    assert state["objects"]["branch_b"]["holder_id"] == "player"
    # The expanded South House footprint now blocks the old straight diagonal.
    state = walk(http, state, 36, 50)
    state = walk(http, state, 34, 51)
    blocked = action(http, state, "take bucket hessa", ["bucket_hessa"], "early-bucket").json()["state"]
    assert blocked["last_action"]["category"] == "blocked"
    assert blocked["objects"]["bucket_hessa"]["owner_id"] == "npc_hessa_marr"
    state = action(http, blocked, "ask Hessa for work", ["npc_hessa_marr"], "ask").json()["state"]
    agreement = state["agreements"]["hessa_debris"]
    assert agreement["status"] == "accepted"
    repeated = action(http, state, "ask Hessa for work", ["npc_hessa_marr"], "ask-again").json()["state"]
    assert repeated["last_action"]["category"] == "blocked"
    state = action(http, repeated, "give branch a to Hessa", ["branch_a", "npc_hessa_marr"], "give").json()["state"]
    assert state["objects"]["branch_a"]["holder_id"] == "npc_hessa_marr"
    assert state["objects"]["branch_a"]["owner_id"] is None
    state = action(http, state, "drop branch b", ["branch_b"], "deliver").json()["state"]
    assert state["agreements"]["hessa_debris"]["status"] == "fulfilled"
    assert len(state["agreements"]["hessa_debris"]["evidence_event_ids"]) == 2
    state = action(http, state, "take bucket hessa", ["bucket_hessa"], "bucket").json()["state"]
    assert state["objects"]["bucket_hessa"]["owner_id"] == "npc_hessa_marr"
    assert state["objects"]["bucket_hessa"]["holder_id"] == "player"
    state = action(http, state, "fill bucket hessa", ["bucket_hessa"], "fill").json()["state"]
    assert state["objects"]["bucket_hessa"]["water_l"] == 1
    assert state["objects"]["trough_hessa"]["water_l"] == 79
    state = action(http, state, "pour bucket hessa", ["bucket_hessa"], "pour").json()["state"]
    assert state["objects"]["bucket_hessa"]["water_l"] == 0
    assert state["objects"]["trough_hessa"]["water_l"] + state["water_spilled_l"] == 80
