from fastapi.testclient import TestClient
from collections import deque
import app as service


def test_building_and_tree_geometry_rejects_moves_without_mutating_save(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "feel.sqlite3")
    http = TestClient(service.app)
    state = http.post("/runs", json={}).json()
    assert state["geometry_version"] == 3
    # Walk along the southern edge of the inn and then attempt to enter its footprint.
    destinations = [(48, y) for y in range(67, 49, -1)] + [(x, 50) for x in range(47, 33, -1)]
    for x, y in destinations:
        response = http.post(f"/runs/{state['run_id']}/move", json={
            "x": x, "y": y, "expected_version": state["event_seq"],
            "request_id": f"move-{state['event_seq']}"})
        assert response.status_code == 200, response.text
        state = response.json()["state"]
    blocked = http.post(f"/runs/{state['run_id']}/move", json={
        "x": 34, "y": 49, "expected_version": state["event_seq"], "request_id": "building"})
    assert blocked.status_code == 403
    assert http.get(f"/runs/{state['run_id']}").json() == state


def test_geometry_leaves_all_npcs_and_resources_accessible():
    rectangles = service.WORLD_GEOMETRY["buildings"] + service.WORLD_GEOMETRY["obstacles"]
    points = service.NPCS + list(service.m2.seed_m2(service.SEED_VERSION)["objects"].values())
    for point in points:
        for rectangle in rectangles:
            x, y, w, h = rectangle["cells"]
            assert not (x <= point["x"] < x + w and y <= point["y"] < y + h), (point["id"], rectangle["name"])
    blocked = {
        (cx, cy)
        for rectangle in rectangles
        for x, y, w, h in [rectangle["cells"]]
        for cx in range(x, x + w)
        for cy in range(y, y + h)
    }
    seen = {(48, 68)}
    frontier = deque(seen)
    while frontier:
        x, y = frontier.popleft()
        for neighbor in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            nx, ny = neighbor
            if (0 <= nx < 96 and 9 <= ny < 72 and neighbor not in blocked
                    and neighbor not in seen):
                seen.add(neighbor)
                frontier.append(neighbor)
    for point in points:
        assert (point["x"], point["y"]) in seen, point["id"]
