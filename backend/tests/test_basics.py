"""The basic training levels (D-59), each played through every step with scripted models: any way that gets the
outcome counts (checks are code, never the wording), the story asks only what its step teaches, and the level ends
in its complete state."""

from test_craft import attempt, judged
from test_encounter import post, world  # noqa: F401  (the fixture is used by name)
from test_golden import beat, new_run, settle
from test_levels import read
from test_talk import said

import cast
import content
import paths
import store
import views

WENNA, PIP, ADA = "npc_wenna_ash", "npc_pip_ash", "npc_ada_miller"


def at_step(state) -> str:
    progress = state.get("tutorial") or {}
    steps = content.LEVELS[state["scenario"]]["steps"]
    return "done" if progress.get("done") else steps[progress["step"]]["id"]


def ui(world, state, key):
    return world.http.post(f"/runs/{state['run_id']}/tutorial/ui", json={"key": key}).json()["state"]


def walk(http, state, x, y):
    """Walk to (x, y), or the nearest open cell to it, around whatever stands in the way: on any map."""
    start = (state["player"]["x"], state["player"]["y"])
    previous, steps = paths.bfs(start, paths.grid(state), 400)
    goal = min(steps, key=lambda c: (abs(c[0] - x) + abs(c[1] - y), steps[c]))
    path = []
    while goal != start:
        path.append(list(goal))
        goal = previous[goal]
    path.reverse()
    for i in range(0, len(path), 20):
        body = {
            "cells": path[i : i + 20],
            "expected_version": state["event_seq"],
            "request_id": f"walk-{state['event_seq']}",
        }
        reply = http.post(f"/runs/{state['run_id']}/move", json=body)
        assert reply.status_code == 200, reply.text
        state = reply.json()["state"]
    return state


def next_to(world, state, npc_id):
    person = cast.find(state["npcs"], npc_id)
    return walk(world.http, state, person["x"], person["y"] + 1)


def test_a_cup_of_water(world):
    state = new_run(world, scenario="cup_of_water")
    assert {n["id"] for n in state["npcs"]} == {WENNA, PIP, ADA} and (
        state["player"]["x"],
        state["player"]["y"],
    ) == (20, 23)
    state = read(world, state)  # welcome
    assert at_step(state) == "walk"
    state = read(world, state)
    state = next_to(world, state, WENNA)
    state = beat(world, state)
    assert at_step(state) == "talk"
    state = read(world, state)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": WENNA, "text": "Good morning. Are you all right?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "look"
    asked = [c for c in state["learned"] if c.get("asks")]
    assert asked and not views.lead_done(state, asked[0])  # Her water: a thing to do, not done yet.
    state = read(world, state)
    state = ui(world, state, "inspect")
    state = read(world, state)
    cup = state["objects"]["cup_wenna"]
    state = walk(world.http, state, cup["x"], cup["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "cup_wenna"})["state"]
    state = read(world, state)
    assert at_step(state) == "pack"
    state = ui(world, state, "pack")
    state = read(world, state)
    assert at_step(state) == "fill"
    world.rulings.append(
        attempt(judged("fill", fill={"container_id": "cup_wenna", "source_id": "bucket_well", "litres": 0.3}))
    )
    state = post(world, state, "craft", {"text": "fill the cup from the well bucket", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "give" and state["objects"]["cup_wenna"]["water_l"] > 0
    state = read(world, state)
    state = next_to(world, state, WENNA)
    world.rulings.append(attempt(judged("give", give={"item_ids": ["cup_wenna"], "recipient_id": WENNA})))
    state = post(world, state, "craft", {"text": "give the cup of water to Wenna", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "journal" and views.lead_done(state, asked[0])
    assert any("mill" in c["lead"] for c in state["learned"])  # What she tells you after: a lead onward.
    state = read(world, state)
    state = ui(world, state, "journal")
    state = read(world, state)
    assert at_step(state) == "device"
    state = post(world, state, "device/ask", {"question": "Who's Ada?"})["state"]
    state = read(world, beat(world, state))
    assert at_step(state) == "ada"  # It ends with Ada, who heard what you did from Pip, not from you.
    state = settle(
        world,
        state,
        lambda s: any(
            h["from"] == PIP for h in (cast.find(s["npcs"], ADA)["mind"].get("knows") or {}).get("heard", [])
        ),
    )
    state = next_to(world, state, ADA)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": ADA, "text": "Good morning. I'm new here."})["state"]
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)
    assert any("drew Gran's water" in m["summary"] for m in cast.find(state["npcs"], ADA)["mind"]["memories"])
    assert world.http.get(f"/runs/{state['run_id']}/result").json()["done"]


ODO = "npc_odo_tinker"


def made(name, consumes, materials, flags=("flexible",)):
    """A judged make: something new from these things."""
    return judged(
        "make",
        new_object={
            "name": name,
            "description": f"A {name}, freshly made.",
            "materials": materials,
            "consumes": consumes,
            "tools_used": [],
            "mass_kg": 0.05,
            "length_m": 1.0,
            "capacity_l": None,
            "rated_load_kg": None,
            "flags": list(flags),
            "capabilities": [],
        },
    )


def test_the_tinkers_book(world):
    state = new_run(world, scenario="tinkers_book")
    assert state["objects"]["flax_tinker"]["owner_id"] == ODO and "lent_to" not in state["objects"]["flax_tinker"]
    state = read(world, state)  # welcome
    state = read(world, state)
    state = next_to(world, state, ODO)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": ODO, "text": "Good day. Can I help?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "book" and state["objects"]["flax_tinker"]["lent_to"] == "player"  # His to lend.
    state = read(world, state)
    book = state["objects"]["book_tinker"]
    state = walk(world.http, state, book["x"], book["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "book_tinker"})["state"]
    state = read(world, state)
    assert at_step(state) == "read"
    state = ui(world, state, "book")
    state = read(world, state)
    assert at_step(state) == "rope"
    state = walk(world.http, state, 5, 6)
    world.rulings.append(attempt(made("flax rope", ["flax_tinker"], ["flax"], ("flexible", "tieable"))))
    state = post(world, state, "craft", {"text": "twist the flax fibres into a rope", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "fail"
    state = read(world, state)
    world.rulings.append(
        attempt(judged("make", outcome="failed", reason="Sawdust has no long fibres: it crumbles instead of twisting."))
    )
    state = post(world, state, "craft", {"text": "twist the sawdust into a rope", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "torch"
    state = read(world, state)
    state = walk(world.http, state, 15, 12)
    torch = made(
        "pitch torch", ["stick_tinker", "rag_tinker"], ["wood", "linen", "pine pitch"], ("rigid", "combustible")
    )
    world.rulings.append(attempt(torch))
    state = post(world, state, "craft", {"text": "wrap the rag on the stick and dip it in pitch", "selected_ids": []})[
        "state"
    ]
    state = beat(world, state)
    assert at_step(state) == "sling"
    state = read(world, state)
    state = walk(world.http, state, 5, 13)
    world.rulings.append(attempt(made("leather sling", ["leather_tinker", "twine_tinker"], ["leather", "hemp"])))
    state = post(world, state, "craft", {"text": "make a sling", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "give"
    state = read(world, state)
    mine = [
        o["id"] for o in state["objects"].values() if o.get("created_by") == "player" and o["holder_id"] == "player"
    ]
    assert len(mine) == 3
    state = next_to(world, state, ODO)
    world.rulings.append(attempt(judged("give", give={"item_ids": mine, "recipient_id": ODO})))
    state = post(world, state, "craft", {"text": "give Odo the rope, the torch and the sling", "selected_ids": []})[
        "state"
    ]
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)
    order = next(c for c in state["learned"] if c.get("asks"))
    assert views.lead_done(state, order) and any("soldier" in c["lead"] for c in state["learned"])


def test_the_level_report_reads_what_was_played(world):
    """tools/level_report.py: journeys, times per step and attempts, from the saves alone (D-59)."""
    import importlib.util
    from pathlib import Path

    test_a_cup_of_water(world)
    spec = importlib.util.spec_from_file_location(
        "level_report", Path(__file__).parents[2] / "tools" / "level_report.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    with store.db() as connection:
        lines = tool.report(connection, content.LEVELS["cup_of_water"])
    text = "\n".join(lines)
    assert "Journeys: 1 started, 1 finished." in text and "| 7 fill |" in text
    fill = next(line for line in lines if line.startswith("| 7 fill |"))
    assert "| 1 / 0 |" in fill  # One attempt in that step, and it worked.


HAL = "npc_hal_brand"


def facing(state, npc_id):
    person = cast.find(state["npcs"], npc_id)
    dx, dy = person["x"] - state["player"]["x"], person["y"] - state["player"]["y"]
    length = max(1e-6, (dx * dx + dy * dy) ** 0.5)
    return [dx / length, dy / length]


def test_the_training_yard(world):
    state = new_run(world, scenario="training_yard")
    state = read(world, state)
    state = read(world, state)
    state = next_to(world, state, HAL)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": HAL, "text": "I'd like to learn how to fight."})["state"]
    state = beat(world, state)
    assert at_step(state) == "arm" and state["objects"]["practice_sword_yard"]["holder_id"] == "player"
    state = read(world, state)
    state = post(world, state, "equip", {"object_id": "practice_sword_yard", "slot": "right"})["state"]
    state = post(world, state, "equip", {"object_id": "wicker_shield_yard", "slot": "left"})["state"]
    assert at_step(state) == "swing"
    state = read(world, state)
    state = post(world, state, "strike", {"hand": "right", "facing": [0.0, -1.0]})["state"]
    assert at_step(state) == "guard"  # A swing moves the story on at once.
    state = beat(world, state)
    state = read(world, state)
    state = post(world, state, "guard", {"raised": True, "facing": facing(state, HAL)})["state"]
    assert at_step(state) == "block"
    state = read(world, state)
    for _ in range(30):  # Hal comes on guard, winds up, and the blow meets the shield.
        if at_step(state) != "block":
            break
        state = post(world, state, "guard", {"raised": True, "facing": facing(state, HAL)})["state"]
        state = beat(world, state)
    assert at_step(state) == "bout" and state["fight"]["spar"]
    state = read(world, state)
    state = post(world, state, "guard", {"raised": False})["state"]
    for _ in range(60):
        if at_step(state) == "done":
            break
        state = (
            next_to(world, state, HAL) if cast.distance(cast.find(state["npcs"], HAL), state["player"]) > 1.5 else state
        )
        state = post(world, state, "strike", {"hand": "right", "target_id": HAL, "facing": facing(state, HAL)})["state"]
        state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)
    assert not state.get("barred_until") and state["player"].get("alive", True)  # Practice: nobody is arrested or hurt.


BREA, TAM = "npc_brea_healer", "npc_tam_drover"


def remedy_made(state):
    return next(
        o["id"] for o in state["objects"].values() if o.get("created_by") == "player" and o["holder_id"] == "player"
    )


def test_patched_up(world):
    state = new_run(world, scenario="patched_up")
    cut = next(c for c in state["player"]["conditions"] if c["kind"] == "bleeding")
    assert cut["treated"] == 0  # Hurt from the start.
    state = read(world, state)
    assert at_step(state) == "wounds"
    state = read(world, state)
    state = ui(world, state, "pack")
    state = read(world, state)
    state = next_to(world, state, BREA)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": BREA, "text": "Could I use some of your linen?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "bandage" and state["objects"]["linen_brea"]["lent_to"] == "player"
    state = read(world, state)
    linen = state["objects"]["linen_brea"]
    state = walk(world.http, state, linen["x"], linen["y"] + 1)
    world.rulings.append(attempt(made("linen bandage", ["linen_brea"], ["linen"])))
    state = post(world, state, "craft", {"text": "tear the linen into a bandage", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "self"
    state = read(world, state)
    bandage = remedy_made(state)
    index = next(i for i, c in enumerate(state["player"]["conditions"]) if c["kind"] == "bleeding")
    state = post(world, state, "treat", {"object_id": bandage, "patient_id": "player", "condition": index})["state"]
    state = beat(world, state)
    assert at_step(state) == "tam"
    state = read(world, state)
    assert any(c["kind"] == "burn" for c in cast.find(state["npcs"], TAM)["conditions"])
    state = next_to(world, state, TAM)
    state = beat(world, state)
    assert at_step(state) == "poultice"
    state = read(world, state)
    leaves = state["objects"]["plantain_brea"]
    state = walk(world.http, state, leaves["x"], leaves["y"] + 1)
    world.rulings.append(attempt(made("plantain poultice", ["plantain_brea"], ["plantain", "leaf"])))
    state = post(world, state, "craft", {"text": "crush the plantain into a poultice", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "treat"
    state = read(world, state)
    state = next_to(world, state, TAM)
    poultice = remedy_made(state)
    world.rulings.append(
        attempt(judged("treat", treat={"remedy_id": poultice, "patient_id": TAM, "condition": "burn"}))
    )
    state = post(world, state, "craft", {"text": "lay the poultice on Tam's hand", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "rewind"
    state = read(world, state)
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


ULF = "npc_ulf_charcoal"


def test_fire_and_water(world):
    state = new_run(world, scenario="fire_and_water")
    state = read(world, state)
    state = read(world, state)
    state = next_to(world, state, ULF)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": ULF, "text": "Can I help?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "fill"
    state = read(world, state)
    pot = state["objects"]["pot_ulf"]
    state = walk(world.http, state, pot["x"], pot["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "pot_ulf"})["state"]
    state = walk(world.http, state, 27, 12)
    world.rulings.append(
        attempt(judged("fill", fill={"container_id": "pot_ulf", "source_id": "river_ulf", "litres": 2.0}))
    )
    state = post(world, state, "craft", {"text": "fill the pot from the river", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "kindle"
    state = read(world, state)
    for oid in ("flint_ulf", "steel_ulf", "tinder_ulf", "kindling_ulf", "logs_ulf"):
        thing = state["objects"][oid]
        state = walk(world.http, state, thing["x"], thing["y"] + 1)
        state = post(world, state, "quick", {"verb": "take", "object_id": oid})["state"]
    state = walk(world.http, state, 17, 15)
    fire = {
        "name": "campfire",
        "description": "A crackling fire in the stone ring.",
        "materials": ["wood", "grass"],
        "consumes": ["tinder_ulf", "kindling_ulf", "logs_ulf"],
        "tools_used": ["flint_ulf", "steel_ulf"],
        "mass_kg": 4.0,
        "length_m": None,
        "capacity_l": None,
        "rated_load_kg": None,
        "flags": ["heat_source", "light_source"],
        "capabilities": [],
        "burning": True,
    }
    world.rulings.append(attempt(judged("make", new_object=fire)))
    state = post(world, state, "craft", {"text": "light a fire in the pit", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "boil"
    state = read(world, state)
    fire_id = next(o["id"] for o in state["objects"].values() if o.get("feature") == "fire" and o.get("burning"))
    pit = state["objects"]["pit_ulf"]  # Made beside Ulf's pit, though the judge didn't name it: it burns in it.
    assert (state["objects"][fire_id]["x"], state["objects"][fire_id]["y"]) == (pit["x"], pit["y"])
    world.rulings.append(
        attempt(
            judged(
                "change",
                change={
                    "target_id": "pot_ulf",
                    "temperature": "boiling",
                    "burning": None,
                    "heat_source_id": fire_id,
                    "pour_into_id": None,
                    "pour_litres": None,
                },
            )
        )
    )
    state = post(world, state, "craft", {"text": "boil the water on the fire", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "give"
    state = read(world, state)
    state = next_to(world, state, ULF)
    world.rulings.append(attempt(judged("give", give={"item_ids": ["pot_ulf"], "recipient_id": ULF})))
    state = post(world, state, "craft", {"text": "give Ulf the pot", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "out"
    state = read(world, state)
    state = walk(world.http, state, 17, 15)
    world.rulings.append(
        attempt(
            judged(
                "change",
                change={
                    "target_id": fire_id,
                    "temperature": None,
                    "burning": False,
                    "heat_source_id": None,
                    "pour_into_id": None,
                    "pour_litres": None,
                },
            )
        )
    )
    state = post(world, state, "craft", {"text": "heap earth over the fire", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


DORAN, IVO, WYNN = "npc_doran_inn", "npc_ivo_carter", "npc_wynn_pilgrim"


def test_the_common_room(world):
    state = new_run(world, scenario="common_room")
    state = read(world, state)
    state = read(world, state)
    state = next_to(world, state, DORAN)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": DORAN, "text": "Good evening. Busy night?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "ask"
    state = read(world, state)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": DORAN, "text": "Can a stranger get into the city?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "both" and any(c["npc_id"] == DORAN for c in state["learned"])
    state = read(world, state)
    tankard = state["objects"]["tankard_ivo"]
    state = walk(world.http, state, tankard["x"], tankard["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "tankard_ivo"})["state"]
    state = next_to(world, state, IVO)
    world.rulings.append(attempt(judged("give", give={"item_ids": ["tankard_ivo"], "recipient_id": IVO})))
    state = post(world, state, "craft", {"text": "“You dropped this.” hand Ivo the tankard", "selected_ids": []})[
        "state"
    ]
    state = beat(world, state)
    assert at_step(state) == "group"
    state = read(world, state)
    state = next_to(world, state, WYNN)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": WYNN, "text": "Where are you travelling to?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "away"
    state = read(world, state)
    state = walk(world.http, state, 20, 5)
    state = beat(world, state)
    assert at_step(state) == "people", state.get("encounter")
    state = read(world, state)
    state = ui(world, state, "journal")
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


ADA = "npc_ada_miller"


def test_a_fair_trade(world):
    from test_gate import answers

    state = new_run(world, scenario="fair_trade")
    state = read(world, state)
    state = read(world, state)
    state = next_to(world, state, ADA)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": ADA, "text": "Is there any work going?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "agree"
    deal = next(iter(state["agreements"].values()))
    assert deal["status"] == "proposed" and state["objects"]["pail_ada"]["lent_to"] == "player"
    state = read(world, state)
    world.replies.append(answers("answer", accepts=0.95))
    state = post(world, state, "say", {"npc_id": ADA, "text": "Deal. I'll fill the trough."})["state"]
    state = beat(world, state)
    assert at_step(state) == "journal"
    state = read(world, state)
    state = ui(world, state, "journal")
    state = read(world, state)
    assert at_step(state) == "work"
    pail = state["objects"]["pail_ada"]
    state = walk(world.http, state, pail["x"], pail["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "pail_ada"})["state"]
    state = walk(world.http, state, 29, 12)
    world.rulings.append(
        attempt(judged("fill", fill={"container_id": "pail_ada", "source_id": "race_ada", "litres": 8.0}))
    )
    state = post(world, state, "craft", {"text": "fill the pail at the race", "selected_ids": []})["state"]
    trough = state["objects"]["trough_ada"]
    state = walk(world.http, state, trough["x"], trough["y"] + 1)
    pour = {
        "target_id": "pail_ada",
        "temperature": None,
        "burning": None,
        "heat_source_id": None,
        "pour_into_id": "trough_ada",
        "pour_litres": 8.0,
    }
    world.rulings.append(attempt(judged("change", change=pour)))
    state = post(world, state, "craft", {"text": "pour the pail into the trough", "selected_ids": []})["state"]
    state = beat(world, state)
    assert at_step(state) == "paid", state["objects"]["trough_ada"]["water_l"]
    state = read(world, state)
    state = next_to(world, state, ADA)
    world.replies.append(answers("answer", done=0.9))
    state = post(world, state, "say", {"npc_id": ADA, "text": "The trough's full."})["state"]
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)
    assert (
        state["objects"]["flour_ada"]["holder_id"] == "player" and state["objects"]["flour_ada"]["owner_id"] == "player"
    )


SELA = "npc_sela_potter"


def test_whose_is_it(world):
    state = new_run(world, scenario="whose_is_it")
    state = read(world, state)
    state = read(world, state)
    state = ui(world, state, "inspect")
    state = read(world, state)
    shoe = state["objects"]["horseshoe_market"]
    state = walk(world.http, state, shoe["x"], shoe["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "horseshoe_market"})["state"]
    state = beat(world, state)
    assert at_step(state) == "steal"
    state = read(world, state)
    jug = state["objects"]["jug_sela"]
    state = walk(world.http, state, jug["x"], jug["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "jug_sela"})["state"]
    state = beat(world, state)
    assert at_step(state) == "back"
    state = read(world, state)
    state = next_to(world, state, SELA) if state["objects"]["jug_sela"]["holder_id"] == "player" else state
    world.rulings.append(attempt(judged("give", give={"item_ids": ["jug_sela"], "recipient_id": SELA})))
    state = post(world, state, "craft", {"text": "“I'm sorry.” give the jug back to Sela", "selected_ids": []})["state"]
    state = settle(world, state, lambda s: at_step(s) != "back", limit=20)
    assert at_step(state) == "standing"
    state = read(world, state)
    state = ui(world, state, "journal")
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


MEY = "npc_mey_shepherd"


def test_something_new(world):
    from test_show import show

    state = new_run(world, scenario="something_new")
    state = read(world, state)
    state = read(world, state)
    state = next_to(world, state, MEY)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": MEY, "text": "Is it hard, keeping sheep up here?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "invent" and state["objects"]["lodestone_orrin"]["lent_to"] == "player"
    state = read(world, state)
    for oid in ("needle_mey", "bark_meadow", "lodestone_orrin"):
        thing = state["objects"][oid]
        state = walk(world.http, state, thing["x"], thing["y"] + 1)
        state = post(world, state, "quick", {"verb": "take", "object_id": oid})["state"]
    bowl = state["objects"]["bowl_orrin"]
    state = walk(world.http, state, bowl["x"], bowl["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "bowl_orrin"})["state"]
    state = walk(world.http, state, 26, 12)
    world.rulings.append(
        attempt(judged("fill", fill={"container_id": "bowl_orrin", "source_id": "brook_water", "litres": 0.6}))
    )
    state = post(world, state, "craft", {"text": "fill the bowl at the brook", "selected_ids": []})["state"]
    compass = made("floating needle compass", ["needle_mey", "bark_meadow"], ["iron", "bark"], ("floats", "magnetized"))
    compass["new_object"]["tools_used"] = ["lodestone_orrin", "bowl_orrin"]
    compass["new_object"]["mass_kg"] = sum(state["objects"][i]["mass_kg"] for i in ("needle_mey", "bark_meadow"))
    world.rulings.append(attempt(compass))
    state = post(world, state, "craft", {"text": "rub the needle on the lodestone and float it", "selected_ids": []})[
        "state"
    ]
    state = beat(world, state)
    assert at_step(state) == "show"
    state = read(world, state)
    state = next_to(world, state, MEY)
    made_id = next(o["id"] for o in state["objects"].values() if o.get("created_by") == "player")
    world.rulings.append(
        attempt(show(made_id, "The needle swings round and settles, pointing the same way each time.", audience=[MEY]))
    )
    state = post(world, state, "craft", {"text": "show Mey the floating needle", "selected_ids": []})["state"]
    state = settle(world, state, lambda s: at_step(s) != "show", limit=20)
    assert at_step(state) == "done" and store.finished(state)
    asked = next(c for c in state["learned"] if c.get("asks"))
    assert views.lead_done(state, asked)  # Her problem, answered.
