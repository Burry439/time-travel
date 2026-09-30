"""The behaviour lock (D-58): fixed journeys played through the HTTP API with scripted models, whose final states
must not change unless the game is meant to. Refactors run these before and after.

    GOLDEN_UPDATE=1 pytest tests/test_golden.py   # re-record, only when a change in behaviour is intended

Each journey's final state (and its reload, which must be identical) is compared with tests/golden/<name>.json.
Journey ids are random, so they are replaced by placeholders before comparing."""

import json
import os
import re
from pathlib import Path

import pytest
from test_craft import attempt, judged
from test_encounter import blow, post, world  # noqa: F401  (the fixture is used by name)
from test_gate import answers, walk
from test_talk import said, walk_to

import minds

GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.environ.get("GOLDEN_UPDATE") == "1"


def normalised(state: dict, run_ids: list[str]) -> dict:
    text = json.dumps(state, sort_keys=True, ensure_ascii=False)
    for index, run_id in enumerate(run_ids):
        text = text.replace(run_id, f"<run{index}>").replace(run_id[:8], f"<r{index}>")
    text = re.sub(r"[0-9a-f]{32}", "<hex>", text)  # Anything else random (request ids made from uuid4).
    return json.loads(text)


def check(world, name: str, state: dict, run_ids: list[str]) -> None:
    reloaded = world.http.get(f"/runs/{state['run_id']}").json()
    assert reloaded == state, "the journey doesn't reload to the same state"
    got = normalised(state, run_ids)
    path = GOLDEN / f"{name}.json"
    if UPDATE or not path.exists():
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        if not UPDATE:
            pytest.skip(f"recorded {path.name}; run again to compare")
    expected = json.loads(path.read_text(encoding="utf-8"))
    if got != expected:
        diffs = [key for key in sorted(set(got) | set(expected)) if got.get(key) != expected.get(key)]
        raise AssertionError(f"{name}: the journey ended differently; changed top-level fields: {diffs}")


def new_run(world, **body) -> dict:
    return world.http.post("/runs", json={"mode": "developer", **body}).json()


def beat(world, state, ms=1000):
    return post(world, state, "explore", {"elapsed_ms": ms})["state"]


def settle(world, state, until, limit=200):
    for _ in range(limit):
        if until(state):
            return state
        state = post(world, state, "think", {})["state"] if state.get("pending_minds") else beat(world, state)
    raise AssertionError("condition never held")


def test_golden_hessa_route(world):
    """Water for Hessa, her word to the captain, the captain lets the stranger in, and in they walk."""
    http = world.http
    state = walk_to(http, new_run(world), 45, 52)
    world.rulings.append(attempt(judged("take", take_ids=["gourd_a"]), key="take"))
    state = post(world, state, "craft", {"text": "take the gourd", "selected_ids": ["gourd_a"]})["state"]
    state = walk_to(http, state, 36, 53)  # Beside Hessa and her trough.
    world.replies.append(answers("offer:water_haul"))
    state = post(world, state, "say", {"npc_id": "npc_hessa_marr", "text": "Any way I can help?"})["state"]
    world.replies.append(answers("answer", accepts=0.95))
    state = post(world, state, "say", {"npc_id": "npc_hessa_marr", "text": "Gladly, I'll fetch it."})["state"]
    world.rulings.append(
        attempt(
            judged("fill", fill={"container_id": "gourd_a", "source_id": "trough_hessa", "litres": 1.0}),
            judged("give", give={"item_ids": ["gourd_a"], "recipient_id": "npc_hessa_marr"}),
            key="fill+give",
        )
    )
    state = post(
        world, state, "craft", {"text": "fill the gourd at the trough and give it to Hessa", "selected_ids": []}
    )["state"]
    state = settle(world, state, lambda s: not s.get("pending_minds"))
    world.replies.append(answers("answer", done=0.9))
    state = post(world, state, "say", {"npc_id": "npc_hessa_marr", "text": "Here's your water."})["state"]
    state = settle(
        world,
        state,
        lambda s: any(m["kind"] == "vouch" for m in minds.mind(minds.find(s["npcs"], "npc_roderic_vale"))["memories"]),
    )
    roderic = minds.find(state["npcs"], "npc_roderic_vale")
    state = walk(http, state, roderic["x"], roderic["y"] + 2)
    world.replies.append(answers("admit", reason=0.8, threat=0.1))
    state = post(world, state, "say", {"npc_id": "npc_roderic_vale", "text": "Hessa has spoken for me."})["state"]
    state = walk(http, state, 48, 3)
    assert state["inside_city"]
    check(world, "hessa_route", state, [state["run_id"]])


def test_golden_halt_fight_arrest(world):
    """A guard halts the stranger; a round of talk; a shove makes it a fight; giving up is an arrest."""
    state = new_run(world)
    cells = [[48, y] for y in range(67, 15, -1)]
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i : i + 20]})["state"]
    for _ in range(60):
        if state.get("encounter"):
            break
        state = beat(world, state)
    guard = state["encounter"]["participants"][0]
    world.replies.append(said("ask_back"))
    state = post(world, state, "encounter/act", {"kind": "say", "text": "Just a traveller."})["state"]
    world.rulings.append(blow(guard, "wounded"))
    world.choices.append("listen")
    state = post(world, state, "craft", {"text": "shove the guard", "selected_ids": []})["state"]
    state = beat(world, state, 500)
    state = post(world, state, "act", {"text": "I give up"})["state"]
    for _ in range(5):
        state = beat(world, state)
    assert state["barred_until"] > 0
    check(world, "halt_fight_arrest", state, [state["run_id"]])


def test_golden_make_hold_strike_rewind(world):
    """Pick things up, make a club, take it in hand, swing it, let time pass, then rewind."""
    http = world.http
    state = new_run(world)
    branch, _cord = state["objects"]["branch_a"], state["objects"]["cord_a"]
    state = walk_to(http, state, branch["x"], branch["y"] + 1)
    for oid in ("branch_a", "cord_a"):
        state = post(world, state, "quick", {"verb": "take", "object_id": oid})["state"]
    club = {
        "name": "bound club",
        "description": "A branch with cord wound tight round its grip.",
        "materials": ["wood", "plant fibre"],
        "consumes": ["branch_a", "cord_a"],
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
    state = post(world, state, "equip", {"object_id": made["id"], "slot": "right"})["state"]
    state = post(world, state, "strike", {"hand": "right", "facing": [0.0, -1.0]})["state"]
    for _ in range(4):
        state = beat(world, state)
    first = state["run_id"]
    rewound = http.post(f"/runs/{first}/rewind", json={}).json()
    assert rewound["run_id"] != first
    check(world, "make_hold_strike", state, [first])
    check(world, "rewound", rewound, [first, rewound["run_id"]])


def test_golden_tutorial(world):
    """The first morning: real outcomes where they're cheap (walking, a closer look, picking things up, the pack),
    the developer skip for the rest, and the clock running while Mara fetches Kade and he comes over."""
    http = world.http
    state = new_run(world, scenario="tutorial")
    run = f"/runs/{state['run_id']}"

    def read(state):
        return http.post(f"{run}/tutorial/read", json={"step": state["tutorial"]["step"]}).json()["state"]

    def skip():
        return http.post(f"{run}/tutorial/skip").json()["state"]

    state = read(state)
    state = read(state)
    state = post(world, state, "move", {"cells": [[48, y] for y in range(67, 61, -1)]})["state"]
    state = beat(world, state, 500)
    state = read(state)
    state = http.post(f"{run}/tutorial/ui", json={"key": "inspect"}).json()["state"]
    state = read(state)
    for oid in ("plantain_a", "flint_a", "grass_a"):
        state = post(world, state, "quick", {"verb": "take", "object_id": oid})["state"]
    state = read(state)
    state = http.post(f"{run}/tutorial/ui", json={"key": "pack"}).json()["state"]
    state = post(world, state, "device/ask", {"question": "What now?"})["state"]
    for _ in range(4):  # smithy, talk, remedy, treat
        state = skip()
    state = read(state)
    for _ in range(40):  # Mara goes to Kade, tells him, and they come back.
        state = beat(world, state)
    while state["tutorial"].get("done") is False and state["tutorial"]["step"] < 17:
        state = skip()
    state = read(state)
    state = beat(world, state)
    check(world, "tutorial", state, [state["run_id"]])
