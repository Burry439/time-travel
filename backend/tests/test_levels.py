"""Any level on any map (D-59): a journey in the test room (data/content/levels/test_room.json), a small map with
two people, no guard, no captain and no gate, plays its guided story and every system the village has (walking,
talking, picking up, making, giving, a theft with nobody to call, a fight, the clock) without leaving its map."""

from test_craft import attempt, judged
from test_encounter import blow, post, world  # noqa: F401  (the fixture is used by name)
from test_golden import beat, new_run, settle
from test_talk import said, walk_to

import cast
import clock
import content
import paths
import store

HESSA, TOMAS = "npc_hessa_marr", "npc_tomas_reed"


def read(world, state):
    return world.http.post(f"/runs/{state['run_id']}/tutorial/read", json={"step": state["tutorial"]["step"]}).json()[
        "state"
    ]


def test_a_level_has_its_own_map_people_and_things():
    level = content.LEVELS["test_room"]
    state = {"scenario": "test_room"}
    assert content.map_of(state)["id"] == "test_room" and paths.gate(state) is None
    grid = paths.grid({"scenario": "test_room", "objects": {}})
    assert grid.walkable((0, 0)) and not grid.walkable((20, 0)) and not grid.walkable((9, 6))  # The table.
    assert set(level["cast"]) == {HESSA, TOMAS} and level["hidden"]


def test_a_journey_in_the_test_room_plays_its_story_and_every_system(world):
    http = world.http
    state = new_run(world, scenario="test_room")
    assert {n["id"] for n in state["npcs"]} == {HESSA, TOMAS} and cast.captain(state) is None
    assert {"stick_room", "cord_room", "cup_room", "basin_room", "tree_sapling"} <= set(state["objects"])
    assert (state["player"]["x"], state["player"]["y"]) == (10, 12) and state["objective"] == "Walk to the hearth"

    state = read(world, state)
    state = walk_to(http, state, 3, 4)
    state = beat(world, state)
    assert state["tutorial"]["step"] == 1 and state["objective"] == "Talk to Hessa"
    state = read(world, state)
    hessa = cast.find(state["npcs"], HESSA)
    state = walk_to(http, state, hessa["x"], hessa["y"] + 1)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": HESSA, "text": "Good day to you."})["state"]
    state = beat(world, state)
    assert state["tutorial"]["done"] and state["objective"] == "Try anything"

    stick = state["objects"]["stick_room"]
    state = walk_to(http, state, stick["x"], stick["y"] - 1)
    for oid in ("stick_room", "cord_room"):
        state = post(world, state, "quick", {"verb": "take", "object_id": oid})["state"]
    club = {
        "name": "bound club",
        "description": "A branch with cord wound tight round its grip.",
        "materials": ["wood", "plant fibre"],
        "consumes": ["stick_room", "cord_room"],
        "tools_used": [],
        "mass_kg": 1.2,
        "length_m": 0.9,
        "capacity_l": None,
        "rated_load_kg": None,
        "flags": ["rigid"],
        "capabilities": [],
    }
    world.rulings.append(attempt(judged("make", new_object=club)))
    state = post(world, state, "craft", {"text": "wind the cord round the branch", "selected_ids": []})["state"]
    made = next(o for o in state["objects"].values() if o.get("created_by") == "player")

    cup = state["objects"]["cup_room"]
    state = walk_to(http, state, cup["x"], cup["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "cup_room"})["state"]  # Hessa's: a theft.
    state = settle(world, state, lambda s: not s.get("pending_minds"))
    world.rulings.append(attempt(judged("give", give={"item_ids": ["cup_room"], "recipient_id": HESSA})))
    hessa = cast.find(state["npcs"], HESSA)
    state = walk_to(http, state, hessa["x"], hessa["y"] + 1)
    state = post(world, state, "craft", {"text": "give the cup back to Hessa", "selected_ids": []})["state"]
    assert state["objects"]["cup_room"]["holder_id"] == HESSA

    tomas = cast.find(state["npcs"], TOMAS)
    state = walk_to(http, state, tomas["x"], tomas["y"] + 1)
    state = post(world, state, "equip", {"object_id": made["id"], "slot": "right"})["state"]
    world.rulings.append(blow(TOMAS, "wounded", weapon=made["id"]))
    state = post(world, state, "craft", {"text": "hit Tomas with the club", "selected_ids": []})["state"]

    width, height = content.map_of(state)["size"]
    for _ in range(60):  # A minute through the service, minds and all...
        state = post(world, state, "think", {})["state"] if state.get("pending_minds") else beat(world, state)
    seen = set()
    for _ in range(540):  # ...then nine more on the clock itself: everyone keeps to the room, nobody waits on a gate.
        payload = clock.advance_people(state, 1000)
        state.update(sim_time_ms=state["sim_time_ms"] + 1000, npcs=payload["npcs"])
        store.apply_people(state, payload)
        for person in state["npcs"]:
            assert 0 <= person["x"] < width and 0 <= person["y"] < height, person["id"]
            seen.add((person["id"], person["x"], person["y"]))
    assert len([1 for who, _, _ in seen if who == HESSA]) > 5, "Hessa never walked her round"
    assert state["sim_time_ms"] >= 590_000 and not state.get("inside_city") and not state.get("gate_open")
