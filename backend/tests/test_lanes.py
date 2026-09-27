"""Movement batches and the player's lane: people thinking or the clock never make the player stale."""
from fastapi.testclient import TestClient

import app as service


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service.store, "DB_PATH", tmp_path / "lanes.sqlite3")
    return TestClient(service.app)


def test_a_batch_of_steps_is_one_event(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={}).json()
    reply = http.post(f"/runs/{state['run_id']}/move", json={
        "cells": [[48, 67], [48, 66], [49, 65]], "expected_version": state["event_seq"], "request_id": "batch"})
    assert reply.status_code == 200, reply.text
    moved = reply.json()["state"]
    assert (moved["player"]["x"], moved["player"]["y"]) == (49, 65)
    assert moved["event_seq"] == state["event_seq"] + 1
    assert http.get(f"/runs/{state['run_id']}").json() == moved
    duplicate = http.post(f"/runs/{state['run_id']}/move", json={
        "cells": [[48, 67], [48, 66], [49, 65]], "expected_version": state["event_seq"], "request_id": "batch"})
    assert duplicate.json()["duplicate"] and duplicate.json()["state"]["event_seq"] == moved["event_seq"]


def test_a_blocked_step_keeps_the_steps_before_it(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={}).json()
    # The inn's south house covers x 20-34, y 54-60; (34, 60) is inside it.
    cells = [[x, 68] for x in range(47, 34, -1)] + [[35, 67], [35, 66], [35, 65], [35, 64], [35, 63],
                                                     [35, 62], [35, 61], [34, 60], [34, 59]]
    reply = http.post(f"/runs/{state['run_id']}/move", json={
        "cells": cells, "expected_version": state["event_seq"], "request_id": "into-house"})
    assert reply.status_code == 403
    body = reply.json()
    assert (body["state"]["player"]["x"], body["state"]["player"]["y"]) == (35, 61)
    assert http.get(f"/runs/{state['run_id']}").json() == body["state"]


def test_people_thinking_or_the_clock_do_not_make_the_player_stale(tmp_path, monkeypatch):
    http = client(tmp_path, monkeypatch)
    state = http.post("/runs", json={}).json()
    seen = state["event_seq"]
    ticked = http.post(f"/runs/{state['run_id']}/explore", json={
        "elapsed_ms": 500, "expected_version": seen, "request_id": "beat"}).json()["state"]
    assert ticked["event_seq"] == seen + 1
    # The player still sends the version they last saw: accepted, because a clock beat isn't their action.
    moved = http.post(f"/runs/{state['run_id']}/move", json={
        "x": 48, "y": 67, "expected_version": seen, "request_id": "step"})
    assert moved.status_code == 200, moved.text
    # But a request that hasn't seen the player's own latest action is stale.
    stale = http.post(f"/runs/{state['run_id']}/move", json={
        "x": 48, "y": 66, "expected_version": seen, "request_id": "stale-step"})
    assert stale.status_code == 409
