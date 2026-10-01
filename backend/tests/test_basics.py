"""The basic training levels (D-59), each played through every step with scripted models: any way that gets the
outcome counts (checks are code, never the wording), the story asks only what its step teaches, and the level ends
in its complete state."""

from test_craft import attempt, judged
from test_encounter import post, world  # noqa: F401  (the fixture is used by name)
from test_gate import walk
from test_golden import beat, new_run
from test_levels import read
from test_talk import said

import cast
import content
import store
import views

WENNA = "npc_wenna_ash"


def at_step(state) -> str:
    progress = state.get("tutorial") or {}
    steps = content.LEVELS[state["scenario"]]["steps"]
    return "done" if progress.get("done") else steps[progress["step"]]["id"]


def ui(world, state, key):
    return world.http.post(f"/runs/{state['run_id']}/tutorial/ui", json={"key": key}).json()["state"]


def next_to(world, state, npc_id):
    person = cast.find(state["npcs"], npc_id)
    return walk(world.http, state, person["x"], person["y"] + 1)


def test_a_cup_of_water(world):
    state = new_run(world, scenario="cup_of_water")
    assert {n["id"] for n in state["npcs"]} == {WENNA, "npc_pip_ash"} and (
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
    state = post(world, state, "device/ask", {"question": "What should I do now?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)
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
            "mass_kg": 0.4,
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
