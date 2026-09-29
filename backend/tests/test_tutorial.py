"""The tutorial, "The first morning" (D-50): outcomes, not recipes; the bout; the device; exact replay."""
import copy

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


def beat(state, ms=500):
    state["npcs"], heard, state["player"] = minds.advance_world(state, ms, state["sim_time_ms"])
    for object_id, fields in state.pop("people_objects_changed", {}).items():
        state["objects"][object_id].update(fields)
    state.pop("people_objects_added", None)
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)


def test_a_tutorial_journey_starts_with_the_device_and_kades_practice_gear():
    state = tutorial_state()
    assert state["scenario"] == "tutorial" and at_step(state) == "awake"
    assert state["objective"].startswith("Walk a little way up the road")
    assert state["device_log"] and "device" in state["device_log"][0]["text"]
    assert state["objects"]["practice_staff"]["holder_id"] == "npc_kade_east"
    village_run = service.initial_state({"id": "vil00000", "mode": "developer", "seed_version": service.SEED_VERSION,
                                         "geometry_version": service.GEOMETRY_VERSION})
    assert "tutorial" not in village_run and "practice_staff" not in village_run["objects"]


def test_the_whole_story_moves_on_by_outcomes():
    state = tutorial_state()
    state["player"].update(x=48, y=62)
    tutorial.tick(state)
    assert at_step(state) == "hands"
    carry(state, "branch_a")
    carry(state, "flint_a")
    tutorial.tick(state)
    assert at_step(state) == "smithy"
    jory = npc(state, "npc_jory_venn")
    assert any(c["kind"] == "burn" for c in jory["conditions"])  # His cry, and his burn.
    assert any("tongs slipped" in (e.get("reason") or "") for e in state["journal"]) or jory["mind"]["said"]
    minds.mind(jory).setdefault("talk", []).append({"who": "stranger", "text": "Let me see.", "at": 0})
    tutorial.tick(state)
    assert at_step(state) == "remedy"
    poultice = carry(state, "plantain_a", gear={"kind": "remedy", "class": "poultice", "covers": [], "quality": "fair"})
    tutorial.tick(state)
    assert at_step(state) == "treat"
    burn = next(i for i, c in enumerate(jory["conditions"]) if c["kind"] == "burn")
    assert gear.treat(jory, burn, poultice, state["sim_time_ms"])["ok"]
    tutorial.tick(state)
    assert at_step(state) == "arm"
    kade = npc(state, "npc_kade_east")
    assert kade["mind"]["job"]["kind"] == "approach"  # He comes over.
    kade.update(x=state["player"]["x"] + 1, y=state["player"]["y"])
    tutorial.tick(state)
    assert state["objects"]["practice_staff"]["holder_id"] == "player"  # Lent, not stolen.
    assert state["objects"]["practice_staff"]["lent_to"] == "player"
    assert gear.equip(state, state["player"], state["objects"]["practice_staff"], "right")["ok"]
    tutorial.tick(state)
    assert at_step(state) == "bout" and state["fight"] and state["fight"]["spar"]  # Armed and beside him: the bout.
    result = combat.surrender(state, state["sim_time_ms"])
    assert not result["arrested"] and state["fight"] is None
    tutorial.tick(state)
    assert at_step(state) == "wonder"
    minds.remember(jory, {"kind": "demonstration", "works": True, "clarity": "clear", "severity": 1, "event": 99,
                          "summary": "The stranger showed a lever.", "short": "showed a lever", "victim": None,
                          "source": "witnessed"})
    tutorial.tick(state)
    assert at_step(state) == "done" and state["objective"] == "Get inside the city"
    assert "up to you" in " ".join(line["text"] for line in state["device_log"])


def test_a_player_ahead_of_the_story_skips_what_they_have_done():
    state = tutorial_state()
    state["player"].update(x=48, y=62)
    carry(state, "branch_a")
    carry(state, "flint_a")
    tutorial.tick(state)
    assert at_step(state) == "smithy"  # Two steps at once: "you're ahead of me".


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
        if combat.strike(state, "right", "npc_kade_east", state["sim_time_ms"])["ok"]:
            pass
        beat(state)
    outcomes = [e["category"] for e in state["journal"] if e.get("kind") == "fight"
                and e.get("category") in tutorial.SPAR_OUTCOMES]
    assert outcomes and state["fight"] is None
    assert not state.get("barred_until") and not state.get("subdued_by")  # Nobody arrests anybody.
    assert not kade.get("conditions") and not state["player"].get("conditions")  # Pulled blows: nobody bleeds.
    assert kade.get("alive", True) and not kade.get("down")
    assert not any(m["kind"] == "violence" for n in state["npcs"] for m in (n.get("mind") or {}).get("memories", []))


def test_the_device_reacts_once_to_something_drastic():
    state = tutorial_state()
    npc(state, "npc_darin_ko")["alive"] = False
    assert tutorial.tick(state)
    lines = [line["text"] for line in state["device_log"] if line["kind"] == "reaction"]
    assert len(lines) == 1 and "killed" in lines[0]
    tutorial.tick(state)
    assert len([line for line in state["device_log"] if line["kind"] == "reaction"]) == 1


def test_the_device_knows_only_what_the_stranger_does():
    state = tutorial_state()
    context = tutorial.device_context(state, "What is Oren hiding?")
    flat = str(context)
    assert "secrets" not in flat and "late shifts" not in flat  # Bren's secret about Oren is nowhere in it.
    assert context["tutorial"] and context["step"]["title"] == "Awake" and "Space" in context["controls"]
    assert tutorial.fallback_answer(state) == tutorial.STEPS[0]["hints"][0]


# --- Over HTTP ------------------------------------------------------------------------------------------------

def test_a_tutorial_journey_over_http_progresses_asks_and_replays(world):
    http = world.http
    state = http.post("/runs", json={"mode": "developer", "scenario": "tutorial"}).json()
    assert state["scenario"] == "tutorial" and state["tutorial"]["step"] == 0
    cells = [[48, y] for y in range(67, 61, -1)]
    state = post(world, state, "move", {"cells": cells})["state"]
    state = post(world, state, "explore", {"elapsed_ms": 500})["state"]  # The clock beat checks the story.
    assert state["tutorial"]["step"] == 1
    body = post(world, state, "device/ask", {"question": "What should I do?"})
    assert body["answer"] == tutorial.STEPS[1]["hints"][0]  # No model in tests: the step's written hint.
    state = body["state"]
    assert state["journal"][-1]["kind"] == "device" and state["journal"][-1]["question"] == "What should I do?"
    skipped = http.post(f"/runs/{state['run_id']}/tutorial/skip").json()["state"]
    assert skipped["tutorial"]["step"] == 2 and skipped["objective"].startswith("Someone is hurt")
    assert http.get(f"/runs/{state['run_id']}").json() == skipped  # Replays exactly.
    normal = http.post("/runs", json={"mode": "normal", "scenario": "tutorial"}).json()
    assert http.post(f"/runs/{normal['run_id']}/tutorial/skip").status_code == 403
    assert http.post("/runs", json={"mode": "normal", "scenario": "moon"}).status_code == 422
