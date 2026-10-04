"""Saves store only what changed (D-58): a patch applied to the state before gives the state after, exactly."""

import copy

from test_encounter import post, world  # noqa: F401  (the fixture is used by name)

import patch


def roundtrip(before, after):
    changes = patch.diff(before, after)
    state = copy.deepcopy(before)
    patch.apply(state, changes)
    assert state == after
    return changes


def test_keys_added_changed_and_removed():
    changes = roundtrip({"a": 1, "b": {"c": 2, "d": 3}, "gone": True}, {"a": 1, "b": {"c": 5, "d": 3}, "new": [1]})
    assert changes == {"gone": {"-": 1}, "b": {"c": {"=": 5}}, "new": {"=": [1]}}  # Unchanged keys aren't saved.


def test_people_are_diffed_one_by_one_and_only_what_moved_is_saved():
    before = {"npcs": [{"id": "a", "x": 1, "mind": {"talk": []}}, {"id": "b", "x": 5, "mind": {"talk": []}}]}
    after = copy.deepcopy(before)
    after["npcs"][1]["x"] = 6
    after["npcs"][1]["mind"]["talk"].append({"who": "them", "text": "Hello."})
    assert roundtrip(before, after) == {
        "npcs": {"@": {"b": {"x": {"=": 6}, "mind": {"talk": {"+": [{"who": "them", "text": "Hello."}]}}}}}
    }


def test_lists_that_grow_or_are_walked_say_so_and_anything_else_is_replaced():
    assert roundtrip({"journal": [1, 2]}, {"journal": [1, 2, 3, 4]}) == {"journal": {"+": [3, 4]}}
    assert roundtrip({"path": [[1, 1], [1, 2], [1, 3]]}, {"path": [[1, 3]]}) == {"path": {"<": 2}}
    assert roundtrip({"journal": [1, 2, 3]}, {"journal": [2, 9]}) == {"journal": {"=": [2, 9]}}
    assert "+" in roundtrip({"npcs": [{"id": "a"}]}, {"npcs": [{"id": "a"}, {"id": "b"}]})["npcs"]
    roundtrip({"npcs": [{"id": "a"}, {"id": "b"}]}, {"npcs": [{"id": "b"}, {"id": "a"}]})  # Reordered: replaced.


def test_a_patch_applies_twice_to_two_copies_without_sharing_values():
    before, after = {"objects": {}}, {"objects": {"o": {"id": "o", "tags": ["x"]}}}
    changes = patch.diff(before, after)
    one, two = copy.deepcopy(before), copy.deepcopy(before)
    patch.apply(one, changes)
    patch.apply(two, changes)
    one["objects"]["o"]["tags"].append("y")
    assert two["objects"]["o"]["tags"] == ["x"]


def test_a_real_journey_state_roundtrips():
    import app as service

    run = {
        "id": "p0000000",
        "mode": "developer",
        "seed_version": service.SEED_VERSION,
        "geometry_version": service.GEOMETRY_VERSION,
        "scenario": "cup_of_water",
    }
    before = patch.snapshot(service.initial_state(run))
    after = copy.deepcopy(before)
    after["npcs"][0]["x"] += 1
    after["objects"]["cup_wenna"]["holder_id"] = "player"
    after["journal"].append({"kind": "craft", "reason": "You pick it up."})
    after["tutorial"]["step"] = 3
    del after["objects"]["apple_windfall"]
    changes = roundtrip(before, after)
    assert set(changes) == {"npcs", "objects", "journal", "tutorial"}


def test_a_journey_reloads_exactly_across_checkpoints_and_only_the_newest_are_kept(world, monkeypatch):
    import sqlite3

    import store

    monkeypatch.setattr(store, "CHECKPOINT_EVERY", 3)
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    for _ in range(14):
        state = post(world, state, "explore", {"elapsed_ms": 500})["state"]
    with sqlite3.connect(store.DB_PATH) as connection:
        kept = [row[0] for row in connection.execute("SELECT seq FROM checkpoints WHERE run_id=?", (state["run_id"],))]
    assert sorted(kept) == [9, 12]
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
