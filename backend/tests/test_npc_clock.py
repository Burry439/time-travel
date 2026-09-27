import time

from fastapi.testclient import TestClient

import app as service
import npc_sim


def test_exploration_clock_moves_npcs_without_double_counting_or_offline_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "living.sqlite3")
    http = TestClient(service.app)
    initial = http.post("/runs", json={}).json()
    run_id = initial["run_id"]
    assert initial["seed_version"] >= 3
    assert all("controller" in npc for npc in initial["npcs"])

    state = initial
    for index in range(12):
        request = {"elapsed_ms": 500, "expected_version": state["event_seq"],
                   "request_id": f"beat-{index}"}
        reply = http.post(f"/runs/{run_id}/explore", json=request)
        assert reply.status_code == 200, reply.text
        state = reply.json()["state"]
        if index == 0:
            retry = http.post(f"/runs/{run_id}/explore", json=request).json()
            assert retry["duplicate"] and retry["state"]["sim_time_ms"] == 500
    assert state["sim_time_ms"] == 6000
    assert any((a["x"], a["y"]) != (b["x"], b["y"])
               for a, b in zip(initial["npcs"], state["npcs"]))
    blocked = npc_sim.blocked_cells(service.WORLD_GEOMETRY)
    assert all((n["x"], n["y"]) not in blocked for n in state["npcs"])

    move = http.post(f"/runs/{run_id}/move", json={"x": 48, "y": 67,
        "expected_version": state["event_seq"], "request_id": "first-step"}).json()["state"]
    assert move["sim_time_ms"] == 6000
    time.sleep(0.02)
    assert http.get(f"/runs/{run_id}").json() == move
    http.post(f"/runs/{run_id}/checkpoint")
    assert http.get(f"/runs/{run_id}").json() == move


def test_legacy_journey_keeps_movement_time_and_original_cast(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "legacy.sqlite3")
    http = TestClient(service.app)
    created = http.post("/runs", json={}).json()
    with service.db() as connection:
        connection.execute("UPDATE runs SET seed_version=2,geometry_version=2 WHERE id=?",
                           (created["run_id"],))
    old = http.get(f"/runs/{created['run_id']}").json()
    assert len(old["npcs"]) == 8
    assert http.post(f"/runs/{created['run_id']}/explore", json={
        "elapsed_ms": 500, "expected_version": 0, "request_id": "not-available"}).status_code == 409
    moved = http.post(f"/runs/{created['run_id']}/move", json={
        "x": 48, "y": 67, "expected_version": 0, "request_id": "legacy-step"}).json()["state"]
    assert moved["sim_time_ms"] == 139


def test_full_npc_routines_stay_on_open_cells_and_guards_patrol():
    initial = service.initial_state({"id": "test", "mode": "normal", "seed_version": 3,
                                     "geometry_version": service.GEOMETRY_VERSION})
    npcs = initial["npcs"]
    blocked = npc_sim.blocked_cells(service.WORLD_GEOMETRY)
    visited = {npc["id"]: {(npc["x"], npc["y"])} for npc in npcs}
    for now_ms in range(0, 120_000, 500):
        advanced = npc_sim.advance_npcs(npcs, 500, now_ms, service.WORLD_GEOMETRY)
        for before, after in zip(npcs, advanced):
            old_cell = (before["x"], before["y"])
            new_cell = (after["x"], after["y"])
            assert new_cell not in blocked, after["id"]
            assert abs(old_cell[0] - new_cell[0]) + abs(old_cell[1] - new_cell[1]) <= 2
            visited[after["id"]].add(new_cell)
        npcs = advanced
    for guard_id in ("npc_bren_marr", "npc_oren_dast", "npc_elin_west", "npc_kade_east"):
        assert len(visited[guard_id]) >= 8, guard_id
