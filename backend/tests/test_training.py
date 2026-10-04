"""Training (D-59): the catalogue the Training screen shows, done marks and times from journeys that finished, and
ratings kept beside a journey (never in its replay)."""

from test_encounter import post, world  # noqa: F401  (the fixture is used by name)
from test_golden import beat, new_run
from test_levels import HESSA, read
from test_talk import said, walk_to

import cast
import content
import routes_training
import store


def test_the_catalogue_is_every_level_in_a_track_in_order():
    levels = routes_training.catalogue()
    ids = [level["id"] for level in levels]
    assert "village" not in ids and {"cup_of_water", "test_room"} <= set(ids) and "tutorial" not in ids
    tracks = [track for track, _ in routes_training.TRACKS]
    assert [tracks.index(level["track"]) for level in levels] == sorted(
        tracks.index(level["track"]) for level in levels
    )
    test_room = next(level for level in levels if level["id"] == "test_room")
    assert test_room["hidden"] and test_room["minutes"] and test_room["teaches"] and test_room["blurb"]


def test_every_training_level_says_what_the_screen_needs():
    for level in content.LEVELS.values():
        if level.get("track"):
            assert level["track"] in [track for track, _ in routes_training.TRACKS], level["id"]
            assert isinstance(level["order"], int) and level["minutes"] > 0 and level["teaches"] and level["blurb"]
            assert level.get("steps"), f"{level['id']}: a training level is guided"


def test_a_finished_level_is_marked_done_with_its_time_and_can_be_rated(world):
    http = world.http
    lab = new_run(world, scenario="test_room")  # A developer's (or the lab's scripted) journey: never a done mark.
    state = new_run(world, scenario="test_room", mode="normal")
    assert not store.finished(state) and http.get(f"/runs/{state['run_id']}/result").json()["done"] is False
    state = read(world, state)
    state = walk_to(http, state, 3, 4)
    state = beat(world, state)
    state = read(world, state)
    hessa = cast.find(state["npcs"], HESSA)
    state = walk_to(http, state, hessa["x"], hessa["y"] + 1)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": HESSA, "text": "Good day."})["state"]
    state = beat(world, state)
    assert store.finished(state)
    result = http.get(f"/runs/{state['run_id']}/result").json()
    assert result == {"level": "test_room", "done": True, "seconds": result["seconds"]} and result["seconds"] >= 0
    listed = next(level for level in http.get("/training").json()["levels"] if level["id"] == "test_room")
    assert listed["done"] and listed["best_s"] is not None and lab["mode"] == "developer"
    assert http.post(f"/runs/{state['run_id']}/feedback", json={"rating": "bored"}).status_code == 422
    saved = http.post(
        f"/runs/{state['run_id']}/feedback", json={"rating": "about_right", "comment": "Short and clear."}
    )
    assert saved.status_code == 201
    with store.db() as connection:
        row = connection.execute("SELECT rating, comment FROM feedback WHERE run_id=?", (state["run_id"],)).fetchone()
    assert (row["rating"], row["comment"]) == ("about_right", "Short and clear.")
    assert http.get(f"/runs/{state['run_id']}").json() == state  # The rating isn't part of the journey.
