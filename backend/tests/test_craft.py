"""Crafting slice: the judge is stubbed, so these test what code allows and commits."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as service
import crafting
from ai import illustrator, judge

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4b70000000049454e44ae426082")


def spear(**changes):
    result = {
        "outcome": "success", "reason": "You lash the flint to the branch.", "effort_seconds": 40,
        "clarifying_question": None, "precedent_key": "lash:flint+branch|vine",
        "new_object": {"name": "flint-tipped spear", "description": "A branch with a flint point lashed on.",
                       "materials": ["wood", "flint", "vine"], "consumes": ["branch_a", "flint_a", "vine_a"],
                       "tools_used": [], "mass_kg": 1.9, "length_m": 1.6, "capacity_l": None,
                       "rated_load_kg": None, "flags": ["rigid", "sharp_edge"],
                       "capabilities": [{"text": "can pierce soft things", "status": "expected"}]}}
    for key, value in changes.items():
        if key in result["new_object"]:
            result["new_object"][key] = value
        else:
            result[key] = value
    return result


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "craft.sqlite3")
    monkeypatch.setattr(service, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setattr(service.ai_config, "images_enabled", lambda: True)
    painted = []

    def fake_sprite(record, destination: Path):
        painted.append(record)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(PNG)
        return illustrator.SpriteCall(status="ready", model="stub-image", prompt=illustrator.sprite_prompt(record))

    monkeypatch.setattr(service.illustrator, "generate_sprite", fake_sprite)
    ns = SimpleNamespace(contexts=[], replies=[], painted=painted, http=TestClient(service.app))

    def fake_judge(context):
        ns.contexts.append(context)
        return judge.JudgeCall(status="ok", result=ns.replies.pop(0), model="stub", raw_output="{...}", attempts=1)

    monkeypatch.setattr(service.judge, "judge_craft", fake_judge)
    return ns


def walk_to(http, state, x, y):
    while (state["player"]["x"], state["player"]["y"]) != (x, y):
        px, py = state["player"]["x"], state["player"]["y"]
        step = {"x": px + (x > px) - (x < px), "y": py + (y > py) - (y < py),
                "expected_version": state["event_seq"], "request_id": f"walk-{state['event_seq']}"}
        response = http.post(f"/runs/{state['run_id']}/move", json=step)
        assert response.status_code == 200, response.text
        state = response.json()["state"]
    return state


def craft(http, state, text, request_id, selected=()):
    return http.post(f"/runs/{state['run_id']}/craft", json={
        "text": text, "selected_ids": list(selected), "expected_version": state["event_seq"],
        "request_id": request_id})


def test_success_creates_a_persistent_object_with_provenance_and_sprite(world):
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
    world.replies.append(spear())
    reply = craft(http, state, "lash the flint to the branch with the vine", "spear")
    assert reply.status_code == 200, reply.text
    body = reply.json()
    state = body["state"]
    made = state["objects"]["made_" + str(state["event_seq"])]
    assert made["holder_id"] == "player" and made["owner_id"] == "player"
    assert made["components"] == ["branch_a", "flint_a", "vine_a"]
    assert all(state["objects"][i]["holder_id"] == f"in:{made['id']}" for i in made["components"])
    assert made["created_text"] == "lash the flint to the branch with the vine"
    assert state["last_action"]["category"] == "success" and state["sim_time_ms"] == 40_000
    # Owned items never reach the judge; the context lists only reachable public or carried items.
    offered = {item["id"] for item in world.contexts[0]["available_items"]}
    assert "bucket_hessa" not in offered and {"flint_a", "branch_a", "vine_a"} <= offered
    # Developer runs get the full trace inline.
    assert body["trace"]["judge"]["raw_output"] == "{...}" and body["trace"]["made"] == made["id"]
    # The sprite painted from the validated record, not raw text, and is served.
    assert world.painted[0]["name"] == "flint-tipped spear"
    picture = http.get(f"/assets/{made['sprite_asset_id']}")
    assert picture.status_code == 200 and picture.content == PNG
    # Replay after reload and checkpoint is identical.
    assert http.get(f"/runs/{state['run_id']}").json() == state
    http.post(f"/runs/{state['run_id']}/checkpoint")
    assert http.get(f"/runs/{state['run_id']}").json() == state
    # Idempotent retry returns the same result without calling the judge again.
    retry = craft(http, {"run_id": state["run_id"], "event_seq": 0}, "lash the flint to the branch with the vine", "spear")
    assert retry.json()["duplicate"] and retry.json()["state"] == state and len(world.contexts) == 1
    # The created object works with ordinary quick actions.
    dropped = http.post(f"/runs/{state['run_id']}/actions", json={
        "text": f"drop {made['id']}", "selected_ids": [made["id"]], "expected_version": state["event_seq"],
        "request_id": "drop"}).json()["state"]
    assert dropped["objects"][made["id"]]["holder_id"] is None
    taken = http.post(f"/runs/{state['run_id']}/actions", json={
        "text": f"take {made['id']}", "selected_ids": [made["id"]], "expected_version": dropped["event_seq"],
        "request_id": "take"}).json()["state"]
    assert taken["objects"][made["id"]]["holder_id"] == "player"
    traces = http.get(f"/runs/{state['run_id']}/traces").json()
    assert traces["traces"][0]["request_id"] == "spear" and traces["assets"][0]["status"] == "ready"


@pytest.mark.parametrize("change, note", [
    ({"consumes": ["bucket_hessa"]}, "not available"),
    ({"consumes": ["flint_a", "made_up_iron"]}, "not available"),
    ({"consumes": []}, "at least one consumed item"),
])
def test_invalid_proposals_change_nothing(world, change, note):
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
    world.replies.append(spear(**change))
    body = craft(http, state, "make a spear", "bad").json()
    after = body["state"]
    assert after["last_action"]["category"] == "unresolved"
    assert after["objects"] == state["objects"] and after["sim_time_ms"] == state["sim_time_ms"]
    assert any(note in n for n in body["trace"]["validator"]["notes"])


def test_validator_clamps_mass_strips_invented_material_and_unearned_flags(world):
    http = world.http
    state = walk_to(http, http.post("/runs", json={}).json(), 45, 66)
    world.replies.append(spear(materials=["wood", "flint", "vine", "iron"], mass_kg=50.0,
                               flags=["sharp_edge", "magnetized", "light_source", "ferromagnetic"]))
    state = craft(http, state, "make a magic glowing spear", "clamp").json()["state"]
    made = next(o for o in state["objects"].values() if o["id"].startswith("made_"))
    assert "iron" not in made["materials"]
    assert made["mass_kg"] == pytest.approx(1.2 + 0.3 + 0.4)
    assert made["flags"] == ["sharp_edge"]
    assert {c["text"] for c in made["known_capabilities"] if c["status"] == "untested"} >= {
        "could give light if lit", "might become magnetic if touched to a real magnet"}


@pytest.mark.parametrize("outcome", ["failed", "blocked", "unsupported", "needs_clarification"])
def test_non_success_outcomes_create_nothing(world, outcome):
    http = world.http
    state = walk_to(http, http.post("/runs", json={}).json(), 45, 66)
    world.replies.append(spear(outcome=outcome, clarifying_question="Which end?"))
    body = craft(http, state, "turn the stone into a magnet", "no").json()
    after = body["state"]
    assert after["objects"] == state["objects"]
    assert after["last_action"]["category"] == outcome
    assert (after["sim_time_ms"] > state["sim_time_ms"]) == (outcome == "failed")
    assert "trace" not in body  # Normal runs never expose AI internals.


def test_disabled_ai_is_honest_and_older_journeys_are_refused(world, monkeypatch):
    http = world.http
    monkeypatch.setattr(service.judge, "judge_craft", lambda context: judge.JudgeCall(status="disabled"))
    state = http.post("/runs", json={}).json()
    after = craft(http, state, "make a spear", "offline").json()["state"]
    assert after["last_action"]["category"] == "unresolved"
    assert "OPENAI_API_KEY" in after["last_action"]["reason"] and after["objects"] == state["objects"]
    with service.db() as connection:
        connection.execute("UPDATE runs SET seed_version=3 WHERE id=?", (state["run_id"],))
    old = http.get(f"/runs/{state['run_id']}").json()
    assert craft(http, old, "make a spear", "old").status_code == 409
    assert http.get(f"/runs/{state['run_id']}/traces").status_code == 403


def test_new_road_materials_are_reachable_and_described():
    objects = service.m2.seed_objects(4)
    for oid in service.m2.NEW_PUBLIC_MATERIALS:
        assert objects[oid]["owner_id"] is None and objects[oid]["materials"]
    assert set(service.m2.seed_objects(3)) == {"branch_a", "branch_b", "cord_a", "stone_a",
                                               "bucket_hessa", "trough_hessa", "wood_tomas"}
    assert crafting.placeholder_category(["flint"]) == "stone"


def test_stub_mode_runs_the_real_pipeline_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "stub.sqlite3")
    monkeypatch.setattr(service, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setenv("AI_MODE", "stub")
    http = TestClient(service.app)
    assert http.get("/health").json()["ai"]["mode"] == "stub"
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
    body = craft(http, state, "bundle these", "stub", selected=["flint_a", "vine_a"]).json()
    made = body["state"]["objects"][body["trace"]["made"]]
    assert made["components"] == ["flint_a", "vine_a"] and body["trace"]["judge"]["model"] == "stub"
    assert http.get(f"/assets/{made['sprite_asset_id']}").status_code == 200
