"""The tutorial, "The first morning" (D-50, D-52): linear, card by card; outcomes, not recipes; the bout; the
device; exact replay."""
import pytest

import app as service
import combat
import gear
import minds
import tutorial
import village
from test_encounter import post, world  # noqa: F401


@pytest.fixture(autouse=True)
def quiet_village(monkeypatch):
    monkeypatch.setattr(village, "schedule", lambda state, npcs, now: None)


def tutorial_state():
    return service.initial_state({"id": "tut00000", "mode": "developer", "seed_version": service.SEED_VERSION,
                                  "geometry_version": service.GEOMETRY_VERSION, "scenario": "tutorial"})


def npc(state, npc_id):
    return minds.find(state["npcs"], npc_id)


def at_step(state):
    return tutorial.STEPS[state["tutorial"]["step"]]["id"] if tutorial.active(state) else "done"


def carry(state, oid, **fields):
    obj = state["objects"][oid]
    obj.update(holder_id="player", **fields)
    return obj


def read_and_tick(state):
    """The player presses through the step's cards; then the clock beat checks it."""
    tutorial.read_cards(state)
    return tutorial.tick(state)


def beat(state, ms=500):
    state["npcs"], heard, state["player"] = minds.advance_world(state, ms, state["sim_time_ms"])
    for object_id, fields in state.pop("people_objects_changed", {}).items():
        state["objects"][object_id].update(fields)
    state.pop("people_objects_added", None)
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)


def test_a_tutorial_journey_starts_with_the_device_and_kades_practice_gear():
    state = tutorial_state()
    assert state["scenario"] == "tutorial" and at_step(state) == "welcome" and state["tutorial"]["read"] == -1
    assert state["device_log"] and "device" in state["device_log"][0]["text"]
    assert state["objects"]["practice_staff"]["holder_id"] == "npc_kade_east"
    village_run = service.initial_state({"id": "vil00000", "mode": "developer", "seed_version": service.SEED_VERSION,
                                         "geometry_version": service.GEOMETRY_VERSION})
    assert "tutorial" not in village_run and "practice_staff" not in village_run["objects"]


def test_nothing_counts_until_the_cards_are_read_and_it_is_one_step_at_a_time():
    """D-52: the welcome ('always') waits for its cards; a player already standing in the ring and carrying
    everything still sees every step's cards: each step completes only once its own cards are read."""
    state = tutorial_state()
    state["player"].update(x=48, y=62)
    carry(state, "plantain_a")
    assert not tutorial.tick(state) and at_step(state) == "welcome"
    assert read_and_tick(state) and at_step(state) == "walk"
    assert not tutorial.tick(state) and at_step(state) == "walk"  # In the ring already, but its cards come first.
    assert read_and_tick(state) and at_step(state) == "look"
    tutorial.ui_done(state, "inspect")
    read_and_tick(state)
    assert at_step(state) == "take"  # Never two steps in one tick.
    read_and_tick(state)
    assert at_step(state) == "gather"


def test_the_whole_story_moves_on_by_outcomes():
    state = tutorial_state()
    read_and_tick(state)  # welcome
    state["player"].update(x=48, y=62)
    read_and_tick(state)
    tutorial.ui_done(state, "inspect")
    read_and_tick(state)
    carry(state, "plantain_a")
    read_and_tick(state)
    carry(state, "flint_a")
    read_and_tick(state)
    assert at_step(state) == "gather"  # The dry grass too.
    carry(state, "grass_a")
    read_and_tick(state)
    assert at_step(state) == "pack"
    tutorial.ui_done(state, "pack")
    read_and_tick(state)
    assert at_step(state) == "smithy"
    jory = npc(state, "npc_jory_venn")
    assert any(c["kind"] == "burn" for c in jory["conditions"])  # His cry, and his burn.
    state["player"].update(x=jory["x"], y=jory["y"] + 1)
    read_and_tick(state)
    assert at_step(state) == "talk"
    minds.mind(jory).setdefault("talk", []).append({"who": "stranger", "text": "Let me see your arm.", "at": 0})
    read_and_tick(state)
    assert at_step(state) == "remedy"
    poultice = state["objects"]["plantain_a"]
    poultice["gear"] = {"kind": "remedy", "class": "poultice", "covers": [], "quality": "fair"}
    read_and_tick(state)
    assert at_step(state) == "treat"
    burn = next(i for i, c in enumerate(jory["conditions"]) if c["kind"] == "burn")
    assert gear.treat(jory, burn, poultice, state["sim_time_ms"])["ok"]
    read_and_tick(state)
    assert at_step(state) == "kade"
    kade = npc(state, "npc_kade_east")
    assert kade["mind"]["job"]["kind"] == "approach"  # He comes over.
    kade.update(x=state["player"]["x"] + 1, y=state["player"]["y"])
    read_and_tick(state)
    assert state["objects"]["practice_staff"]["lent_to"] == "player" and at_step(state) == "arm"  # Lent, not stolen.
    assert gear.equip(state, state["player"], state["objects"]["practice_staff"], "right")["ok"]
    read_and_tick(state)
    assert at_step(state) == "bout" and not state.get("fight")  # The bout waits for its cards...
    read_and_tick(state)
    assert state["fight"] and state["fight"]["spar"]  # ...then, armed and beside him, it begins.
    assert not combat.surrender(state, state["sim_time_ms"])["arrested"] and state["fight"] is None
    tutorial.tick(state)
    assert at_step(state) == "nail"
    carry(state, "nail_a")
    read_and_tick(state)
    assert at_step(state) == "wonder"
    minds.remember(jory, {"kind": "demonstration", "works": True, "clarity": "clear", "severity": 1, "event": 99,
                          "summary": "The stranger struck sparks.", "short": "struck sparks", "victim": None,
                          "source": "witnessed"})
    read_and_tick(state)
    assert at_step(state) == "city"
    read_and_tick(state)
    assert at_step(state) == "done" and state["objective"] == "Get inside the city"
    assert "up to you" in " ".join(line["text"] for line in state["device_log"])


def test_every_step_is_well_formed():
    for step in tutorial.STEPS:
        assert step["cards"] and all(isinstance(c, str) and c for c in step["cards"]), step["id"]
        if step["check"]["kind"] != "always":
            assert step["task"] and step.get("help"), step["id"]
        if step.get("suggest"):
            assert step["suggest"]["text"] and "button" in step["suggest"], step["id"]
        focus = step.get("focus") or {}
        for oid in [focus.get("object")] + focus.get("objects", []):
            assert oid is None or oid in tutorial_state()["objects"], (step["id"], oid)


def test_the_bout_is_practice_no_crime_no_blood_no_arrest():
    state = tutorial_state()
    kade = npc(state, "npc_kade_east")
    state["player"].update(x=48, y=60)
    kade.update(x=49, y=60)
    staff = carry(state, "practice_staff")
    gear.equip(state, state["player"], staff, "right")
    tutorial._do(state, [{"kind": "spar", "npc": "npc_kade_east"}], 0)
    assert state["fight"]["spar"] and gear.held(state, kade, "right")["id"] == "practice_staff_kade"
    for _ in range(40):
        if not state["fight"]:
            break
        kade.update(x=49, y=60)
        combat.strike(state, "right", "npc_kade_east", state["sim_time_ms"])
        beat(state)
    outcomes = [e["category"] for e in state["journal"] if e.get("kind") == "fight"
                and e.get("category") in tutorial.SPAR_OUTCOMES]
    assert outcomes and state["fight"] is None
    assert not state.get("barred_until") and not state.get("subdued_by")  # Nobody arrests anybody.
    assert not kade.get("conditions") and not state["player"].get("conditions")  # Pulled blows: nobody bleeds.
    assert kade.get("alive", True) and not kade.get("down")
    assert not any(m["kind"] == "violence" for n in state["npcs"] for m in (n.get("mind") or {}).get("memories", []))


def test_the_device_reacts_once_to_something_drastic_even_mid_cards():
    state = tutorial_state()
    npc(state, "npc_darin_ko")["alive"] = False
    assert tutorial.tick(state)
    lines = [line["text"] for line in state["device_log"] if line["kind"] == "reaction"]
    assert len(lines) == 1 and "killed" in lines[0]
    tutorial.tick(state)
    assert len([line for line in state["device_log"] if line["kind"] == "reaction"]) == 1


def test_the_device_knows_only_what_the_stranger_does():
    state = tutorial_state()
    read_and_tick(state)
    context = tutorial.device_context(state, "What is Oren hiding?")
    flat = str(context)
    assert "secrets" not in flat and "late shifts" not in flat  # Bren's secret about Oren is nowhere in it.
    assert context["tutorial"] and context["step"]["title"] == "Walking" and "Space" in context["controls"]
    assert tutorial.fallback_answer(state) == tutorial.STEPS[1]["help"][0]


# --- Over HTTP ------------------------------------------------------------------------------------------------

def test_a_tutorial_journey_over_http_reads_progresses_asks_and_replays(world):
    http = world.http
    state = http.post("/runs", json={"mode": "developer", "scenario": "tutorial"}).json()
    run = f"/runs/{state['run_id']}"
    assert state["scenario"] == "tutorial" and state["tutorial"]["step"] == 0
    state = http.post(f"{run}/tutorial/read", json={"step": 0}).json()["state"]
    assert state["tutorial"]["step"] == 1 and state["tutorial"]["read"] == 0  # Welcome read: on to walking.
    state = http.post(f"{run}/tutorial/read", json={"step": 1}).json()["state"]
    cells = [[48, y] for y in range(67, 61, -1)]
    state = post(world, state, "move", {"cells": cells})["state"]
    state = post(world, state, "explore", {"elapsed_ms": 500})["state"]  # The clock beat checks the story.
    assert state["tutorial"]["step"] == 2
    state = http.post(f"{run}/tutorial/read", json={"step": 2}).json()["state"]
    assert http.post(f"{run}/tutorial/ui", json={"key": "teleport"}).status_code == 422
    state = http.post(f"{run}/tutorial/ui", json={"key": "inspect"}).json()["state"]
    assert state["tutorial"]["step"] == 3 and "inspect" in state["tutorial"]["ui_done"]
    body = post(world, state, "device/ask", {"question": "What should I do?"})
    assert body["answer"] == tutorial.STEPS[3]["help"][0]  # No model in tests: the step's written help.
    state = body["state"]
    assert state["journal"][-1]["kind"] == "device" and state["journal"][-1]["question"] == "What should I do?"
    skipped = http.post(f"{run}/tutorial/skip").json()["state"]
    assert skipped["tutorial"]["step"] == 4 and skipped["objective"] == tutorial.STEPS[4]["task"]
    assert http.get(run).json() == skipped  # Replays exactly.
    normal = http.post("/runs", json={"mode": "normal", "scenario": "tutorial"}).json()
    assert http.post(f"/runs/{normal['run_id']}/tutorial/skip").status_code == 403
    assert http.post("/runs", json={"mode": "normal", "scenario": "moon"}).status_code == 422
