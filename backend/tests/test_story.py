"""A guided level's engine (D-50, D-52, D-59), on the training levels: one step at a time, each counting only once
its cards are read; the device's reactions and what it knows; practice bouts; exact replay over HTTP."""

import pytest
from test_basics import walk
from test_encounter import post, world  # noqa: F401  (the fixture is used by name)

import app as service
import cast
import clock
import combat
import content
import device
import encounter
import gear
import rules
import scenario
import village

WENNA, PIP, HAL, BRAM = "npc_wenna_ash", "npc_pip_ash", "npc_hal_brand", "npc_bram_recruit"
CUP = content.LEVELS["cup_of_water"]["steps"]
YARD = content.LEVELS["training_yard"]["steps"]


@pytest.fixture(autouse=True)
def quiet_village(monkeypatch):
    monkeypatch.setattr(village, "schedule", lambda state, npcs, now: None)


def level_state(level):
    return service.initial_state(
        {
            "id": "story000",
            "mode": "developer",
            "seed_version": service.SEED_VERSION,
            "geometry_version": service.GEOMETRY_VERSION,
            "scenario": level,
        }
    )


def npc(state, npc_id):
    return cast.find(state["npcs"], npc_id)


def at_step(state):
    return content.level(state)["steps"][state["tutorial"]["step"]]["id"] if scenario.active(state) else "done"


def carry(state, oid):
    obj = state["objects"][oid]
    obj["holder_id"] = "player"
    return obj


def read_and_tick(state):
    """The player presses through the step's cards; then the clock beat checks it."""
    scenario.read_cards(state)
    return scenario.tick(state)


def beat(state, ms=500):
    state["npcs"], heard, state["player"] = clock.advance_world(state, ms, state["sim_time_ms"])
    for object_id, fields in state.pop("people_objects_changed", {}).items():
        state["objects"][object_id].update(fields)
    state.pop("people_objects_added", None)
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)


def at_step_of(state, step_id):
    steps = content.level(state)["steps"]
    state["tutorial"]["step"] = next(i for i, s in enumerate(steps) if s["id"] == step_id)
    state["tutorial"]["read"] = state["tutorial"]["step"]


def beside_hal(state):
    hal = npc(state, HAL)
    state["player"].update(x=hal["x"] - 1, y=hal["y"])
    return hal


def no_violence(state):
    return not any(m["kind"] == "violence" for n in state["npcs"] for m in (n.get("mind") or {}).get("memories", []))


def test_nothing_counts_until_the_cards_are_read_and_it_is_one_step_at_a_time():
    """D-52: the welcome ('always') waits for its cards; a stranger already beside Wenna, having spoken to her and
    carrying her cup, still sees every step's cards: each step completes only once its own cards are read."""
    state = level_state("cup_of_water")
    wenna = npc(state, WENNA)
    state["player"].update(x=wenna["x"], y=wenna["y"] + 1)
    cast.mind(wenna).setdefault("talk", []).append({"who": "stranger", "text": "Good morning.", "at": 0})
    carry(state, "cup_wenna")
    scenario.tick(state)
    assert at_step(state) == "welcome"
    assert read_and_tick(state) and at_step(state) == "walk"
    scenario.tick(state)
    assert at_step(state) == "walk"  # Beside her already, but its cards come first.
    assert read_and_tick(state) and at_step(state) == "talk"
    assert read_and_tick(state) and at_step(state) == "look"
    scenario.ui_done(state, "inspect")
    read_and_tick(state)
    assert at_step(state) == "take"  # Never two steps in one tick, the cup in hand or not.
    read_and_tick(state)
    assert at_step(state) == "pack"


def test_the_device_reacts_once_to_something_drastic_even_mid_cards():
    state = level_state("cup_of_water")
    npc(state, PIP)["alive"] = False
    assert scenario.tick(state)
    lines = [line["text"] for line in state["device_log"] if line["kind"] == "reaction"]
    assert len(lines) == 1 and "killed" in lines[0]
    scenario.tick(state)
    assert len([line for line in state["device_log"] if line["kind"] == "reaction"]) == 1


def test_the_device_knows_the_step_and_the_controls():
    state = level_state("cup_of_water")
    read_and_tick(state)
    context = device.context(state, "Where do I go?")
    assert context["tutorial"] and context["step"]["title"] == CUP[1]["title"] and "Space" in context["controls"]
    assert device.fallback_answer(state) == CUP[1]["help"][0]


def test_a_level_over_http_reads_progresses_asks_and_replays(world):
    http = world.http
    state = http.post("/runs", json={"mode": "developer", "scenario": "cup_of_water"}).json()
    run = f"/runs/{state['run_id']}"
    state = http.post(f"{run}/tutorial/read", json={"step": 0}).json()["state"]
    assert state["tutorial"]["step"] == 1 and state["tutorial"]["read"] == 0  # Welcome read: on to walking.
    state = http.post(f"{run}/tutorial/read", json={"step": 1}).json()["state"]
    wenna = npc(state, WENNA)
    state = walk(http, state, wenna["x"], wenna["y"] + 1)
    state = post(world, state, "explore", {"elapsed_ms": 500})["state"]  # The clock beat checks the story.
    assert at_step(state) == "talk"
    state = http.post(f"{run}/tutorial/skip").json()["state"]  # Developers may skip a step.
    assert at_step(state) == "look" and state["objective"] == CUP[3]["task"]
    state = http.post(f"{run}/tutorial/read", json={"step": 3}).json()["state"]
    assert http.post(f"{run}/tutorial/ui", json={"key": "teleport"}).status_code == 422
    state = http.post(f"{run}/tutorial/ui", json={"key": "inspect"}).json()["state"]
    assert at_step(state) == "take" and "inspect" in state["tutorial"]["ui_done"]
    body = post(world, state, "device/ask", {"question": "What should I do?"})
    assert body["answer"] == CUP[4]["help"][0]  # No model in tests: the step's written help.
    state = body["state"]
    assert state["journal"][-1]["kind"] == "device" and state["journal"][-1]["question"] == "What should I do?"
    assert http.get(run).json() == state  # Replays exactly.
    normal = http.post("/runs", json={"mode": "normal", "scenario": "cup_of_water"}).json()
    assert http.post(f"/runs/{normal['run_id']}/tutorial/skip").status_code == 403
    assert http.post("/runs", json={"mode": "normal", "scenario": "moon"}).status_code == 422


def test_the_bout_is_practice_no_crime_no_blood_no_arrest():
    state = level_state("training_yard")
    hal = beside_hal(state)
    gear.equip(state, state["player"], carry(state, "practice_sword_yard"), "right")
    scenario.run(state, [{"kind": "spar", "npc": HAL, "with": "practice_sword_hal"}], 0)
    assert state["fight"]["spar"] and gear.held(state, hal, "right")["id"] == "practice_sword_hal"
    for _ in range(40):
        if not state["fight"]:
            break
        hal.update(x=state["player"]["x"] + 1, y=state["player"]["y"])
        combat.strike(state, "right", HAL, state["sim_time_ms"])
        beat(state)
    outcomes = [
        e["category"] for e in state["journal"] if e.get("kind") == "fight" and e.get("category") in rules.SPAR_OUTCOMES
    ]
    assert outcomes and state["fight"] is None
    assert not state.get("barred_until") and not state.get("subdued_by")  # Nobody arrests anybody.
    assert not hal.get("conditions") and not state["player"].get("conditions")  # Pulled blows: nobody bleeds.
    assert hal.get("alive", True) and not hal.get("down")
    assert state["player"].get("health", 100) == 100 and npc(state, HAL).get("health", 100) == 100  # Faded.
    assert no_violence(state) and cast.mind(hal)["feelings"].get("anger", 0) < 0.67  # And it angers nobody.


def test_a_blow_at_hal_during_his_lessons_is_the_bout_not_an_assault():
    """Seen in play (30 Sep 2026, with the first morning's Kade): a punch with an empty hand began a real fight, and
    the stranger was killed. While someone is teaching, any blow at them starts the practice bout (D-53)."""
    state = level_state("training_yard")
    at_step_of(state, "arm")
    beside_hal(state)
    assert combat.strike(state, "left", HAL, state["sim_time_ms"])["ok"]  # Bare fists.
    beat(state, 1000)
    assert state["fight"] and state["fight"]["spar"] and state["fight"]["lethal"][HAL] is False
    assert gear.held(state, npc(state, HAL), "right")["id"] == "practice_sword_hal"
    assert no_violence(state) and "block:spar" in state["tutorial"]["fired"]


def test_in_a_bout_blows_reach_only_the_partner_and_a_late_swing_is_checked():
    """Seen in play (30 Sep 2026): someone stood beside the stranger during the bout; a swing still in the air as it
    ended hit them, and the partner fought for real. In a practice bout the stranger's blows are for the partner
    only, and one that lands after it's over is checked (D-57)."""
    state = level_state("training_yard")
    at_step_of(state, "bout")
    beside_hal(state)
    npc(state, BRAM).update(x=state["player"]["x"], y=state["player"]["y"] + 1)  # Right in front, facing south.
    gear.equip(state, state["player"], carry(state, "practice_sword_yard"), "right")
    scenario.run(state, [{"kind": "spar", "npc": HAL, "with": "practice_sword_hal"}], 0)
    assert combat.strike(state, "right", None, state["sim_time_ms"], [0.0, 1.0])["ok"]
    assert state["player"]["swings"]["right"]["spar_with"] == HAL
    encounter.surrender(state, state["sim_time_ms"])  # The bout ends with the blow still winding up.
    for _ in range(3):
        beat(state, 1000)
    bram = npc(state, BRAM)
    assert bram.get("health", 100) == 100 and bram.get("alive", True)
    assert any("check your swing" in str(e.get("reason", "")) for e in state["journal"])
    assert no_violence(state) and state["player"].get("alive", True) and not state.get("fight")
