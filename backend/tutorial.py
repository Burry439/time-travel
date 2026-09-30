"""The tutorial, "The first morning" (GDD D-50, D-52), and the device from the future that guides it.

A fixed story on the village map with its own small problems (Jory's burn, a sparring bout with Kade, anything the
stranger invents), never the main game's routes. It is linear (D-52): each step's cards are read first (the client
says so: `read`), and only then does its check count, one step at a time. Checks are outcomes in the world decided
by code (so any way the player finds counts), or a ui action the client reports (`ui`: the pack opened, a closer
look). Progress happens only through `tick`, `read` and `ui`, saved as `tutorial` events (see routes_tutorial), so
replay is exact.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import gear
import m2
import minds

ROOT = Path(__file__).resolve().parents[1]
STORY = json.loads((ROOT / "data" / "content" / "tutorial.json").read_text(encoding="utf-8"))
STEPS: list[dict] = STORY["steps"]
SPAR_OUTCOMES = ("spar_won", "spar_lost", "spar_yielded")
JORY, KADE, MARA = "npc_jory_venn", "npc_kade_east", "npc_mara_venn"


# Kade's practice gear, the tutorial's own (lent to the stranger for the bout). The art tool paints these too.
PRACTICE_GEAR = (
    ("practice_staff", "practice staff", 1.2, 1.5, ["wood"], "A smooth ash staff with padded ends, for practice bouts.",
     ["rigid"], {"kind": "weapon", "class": "staff", "covers": [], "quality": "fair"}),
    ("practice_staff_kade", "practice staff", 1.2, 1.5, ["wood"], "Kade's own practice staff, its padding worn thin.",
     ["rigid"], {"kind": "weapon", "class": "staff", "covers": [], "quality": "fair"}),
    ("wicker_shield", "wicker shield", 2.0, None, ["willow", "wood"],
     "A round shield of woven willow on a wooden rim, light and springy.", ["rigid"],
     {"kind": "shield", "class": "improvised", "covers": [], "quality": "fair"}),
)


def active(state: dict) -> bool:
    return bool(state.get("tutorial")) and not state["tutorial"].get("done")


def step(state: dict) -> dict | None:
    return STEPS[state["tutorial"]["step"]] if active(state) else None


def setup(state: dict) -> None:
    """A tutorial journey: Kade's practice gear to lend, and the story at its first step."""
    kade = minds.find(state["npcs"], KADE)
    for oid, name, mass, length, materials, description, flags, record in PRACTICE_GEAR:
        obj = m2._object_record(oid, name, kade["x"], kade["y"], mass, materials, description, flags, length)
        obj.update(owner_id=KADE, holder_id=KADE, capabilities=["carry"], gear=dict(record), no_overlay=True)
        state["objects"][oid] = obj
    state["tutorial"] = {"step": 0, "started_at": 0, "fired": [], "done": False, "reacted": [], "read": -1,
                         "ui_done": []}
    state["device_log"] = []
    state["journal"] = state.get("journal") or []
    _start_step(state, 0)


# --- The story moving on -------------------------------------------------------------------------------------

def read_cards(state: dict) -> bool:
    """The step's cards have been read (the client's Next): from now its check counts."""
    if not active(state) or state["tutorial"].get("read", -1) >= state["tutorial"]["step"]:
        return False
    state["tutorial"]["read"] = state["tutorial"]["step"]
    return True


def ui_done(state: dict, key: str) -> bool:
    """A ui action the tutorial teaches happened (the pack opened, a closer look, the book read)."""
    if not active(state) or key in state["tutorial"].setdefault("ui_done", []):
        return False
    state["tutorial"]["ui_done"].append(key)
    return True


def tick(state: dict) -> bool:
    """React to anything drastic; then, once the current step's cards are read, fire its triggers and complete it
    if its outcome has happened. One step at a time (D-52): the next step waits for its own cards."""
    if not active(state):
        return False
    tutorial = state["tutorial"]
    now = state.get("sim_time_ms", 0)
    changed = _react(state, now)
    current = STEPS[tutorial["step"]]
    if tutorial.get("read", tutorial["step"]) < tutorial["step"]:
        return changed  # Still reading its cards.
    for trigger in current.get("triggers", []):
        key = f"{current['id']}:{trigger['id']}"
        if key not in tutorial["fired"] and holds(state, trigger["when"]):
            tutorial["fired"].append(key)
            _do(state, trigger["do"], now)
            changed = True
    if not holds(state, current["check"]):
        return changed
    _complete(state, current, now)
    return True


def _complete(state: dict, current: dict, now: int) -> None:
    tutorial = state["tutorial"]
    if current.get("done"):
        device_says(state, current["done"], "story")
    _do(state, current.get("on_done", []), now)
    if tutorial["step"] + 1 >= len(STEPS):
        tutorial["done"] = True
        state["objective"] = "Get inside the city"
        return
    tutorial["step"] += 1
    _start_step(state, now)


def skip(state: dict) -> None:
    """Developer: complete the current step as if its outcome had happened."""
    if not active(state):
        return
    tutorial = state["tutorial"]
    current = STEPS[tutorial["step"]]
    now = state.get("sim_time_ms", 0)
    for trigger in current.get("triggers", []):
        key = f"{current['id']}:{trigger['id']}"
        if key not in tutorial["fired"] and trigger["id"] != "spar":
            tutorial["fired"].append(key)
            _do(state, trigger["do"], now)
    tutorial["read"] = tutorial["step"]
    _complete(state, current, now)


def _start_step(state: dict, now: int) -> None:
    current = STEPS[state["tutorial"]["step"]]
    state["tutorial"]["started_at"] = now
    state["objective"] = current.get("task") or current["title"]
    for line in current.get("cards", []):
        device_says(state, line, "story")
    _do(state, current.get("on_start", []), now)


def _react(state: dict, now: int) -> bool:
    """The device notices anything drastic, once each: a death, an arrest, the stranger dying."""
    tutorial = state["tutorial"]
    changed = False
    seen = {
        "dead": not state["player"].get("alive", True),
        "arrested": int(state.get("barred_until") or 0) > now,
        "killed": any(not n.get("alive", True) for n in state["npcs"]),
    }
    for kind, happened in seen.items():
        if happened and kind not in tutorial["reacted"]:
            tutorial["reacted"].append(kind)
            device_says(state, STORY["reactions"][kind], "reaction")
            changed = True
    return changed


def device_says(state: dict, text: str, kind: str, question: str | None = None) -> None:
    entry = {"at": state.get("sim_time_ms", 0), "text": text, "kind": kind}
    if question:
        entry["question"] = question
    state.setdefault("device_log", []).append(entry)
    state["device_log"] = state["device_log"][-60:]
    state.setdefault("journal", []).append({"kind": "device", "category": kind, "reason": text,
                                            **({"question": question} if question else {})})


# --- Outcomes and triggers ------------------------------------------------------------------------------------

def carried(state: dict) -> list[dict]:
    """What the stranger carries in the pack or hands (not what they wear)."""
    worn = {oid for slot, oid in (state["player"].get("equipped") or {}).items() if slot in gear.COVERS}
    return [o for o in state["objects"].values() if o.get("holder_id") == "player" and o["id"] not in worn]


def holding_weapon(state: dict) -> bool:
    return any((obj := gear.held(state, state["player"], hand)) and gear.of(obj)["kind"] == "weapon"
               for hand in gear.HAND_SLOTS)


def holds(state: dict, condition: dict) -> bool:
    kind = condition["kind"]
    here = minds.player_cell(state)
    if kind == "always":
        return True
    if kind == "near":
        return math.dist(here, tuple(condition["cell"])) <= condition["within"]
    if kind == "carrying":
        return len(carried(state)) >= condition["count"]
    if kind == "carrying_id":
        held = {o["id"] for o in carried(state)}
        return all(i in held for i in condition["ids"])
    if kind == "ui":
        return condition["key"] in (state.get("tutorial") or {}).get("ui_done", [])
    if kind == "talked_to":
        npc = minds.find(state["npcs"], condition["npc"])
        return bool(npc) and any(t.get("who") == "stranger" for t in (npc.get("mind") or {}).get("talk", []))
    if kind == "carrying_remedy":
        return any((remedy := gear.remedy_for(o)) and condition["treats"] in remedy["treats"] for o in carried(state))
    if kind == "condition_treated":
        npc = minds.find(state["npcs"], condition["npc"])
        wounds = [c for c in (npc or {}).get("conditions", []) if c["kind"] == condition["condition"]]
        return bool(npc) and (not wounds or all(c.get("treated", 0) > 0 for c in wounds))
    if kind == "holding_weapon":
        return holding_weapon(state)
    if kind == "npc_near":
        npc = minds.find(state["npcs"], condition["npc"])
        return bool(npc) and npc.get("alive", True) and math.dist(minds._cell(npc), here) <= condition["within"]
    if kind == "ready_to_spar":
        npc = minds.find(state["npcs"], condition["npc"])
        return (bool(npc) and npc.get("alive", True) and not npc.get("down") and not state.get("fight")
                and holding_weapon(state) and math.dist(minds._cell(npc), here) <= condition["within"])
    if kind == "bout_over":
        return any(e.get("kind") == "fight" and e.get("category") in SPAR_OUTCOMES for e in state.get("journal", []))
    if kind == "demonstration_seen":
        return any(m.get("kind") == "demonstration" and m.get("works", True) and m.get("clarity") == "clear"
                   for n in state["npcs"] for m in (n.get("mind") or {}).get("memories", []))
    raise ValueError(f"Unknown tutorial condition {kind}")


def _do(state: dict, actions: list[dict], now: int) -> None:
    import combat  # combat imports minds; tutorial is imported by store's callers
    for action in actions:
        npc = minds.find(state["npcs"], action.get("npc", ""))
        kind = action["kind"]
        if kind == "npc_says" and npc and npc.get("alive", True):
            minds._say(npc, action["text"], now, state, state["journal"])
            minds.mind(npc).setdefault("talk", []).append({"who": "them", "text": action["text"], "at": now})
        elif kind == "approach" and npc and npc.get("alive", True) and not npc.get("down"):
            minds._set_job(npc, {"kind": "approach", "target": "player", "stop": 1.5, "speed": "walk",
                                 "then": "tutorial"}, now)
        elif kind == "lend" and npc:
            for oid in action["objects"]:
                obj = state["objects"].get(oid)
                if obj and obj.get("holder_id") == npc["id"]:
                    obj.update(holder_id="player", lent_to="player")
        elif kind == "hurt" and npc and npc.get("alive", True):  # The story's own problem: Jory's burn.
            wound = action["condition"]
            if not any(c["kind"] == wound["kind"] for c in npc.get("conditions", [])):
                gear.add_condition(npc, wound, now)
                npc["health"] = max(1, npc.get("health", 100) - wound.get("severity", 10))
        elif kind == "spar" and npc:
            staff = state["objects"].get("practice_staff_kade")
            if staff and staff.get("holder_id") == npc["id"]:
                npc.setdefault("equipped", {})["right"] = staff["id"]
            combat.start(state, [npc["id"]], now, "spar", lethal=False)


# --- What the device is told when asked -----------------------------------------------------------------------

CONTROLS = ("Move: WASD or arrows, Shift to run. Hover to see what things are; right-click to look closer. "
            "Left-click to talk to someone or pick something up. T (or Enter) to say or do anything in your own "
            "words. E acts on the nearest thing. I: Pack & gear (hold, wear, treat wounds). J: the journal. "
            "Space: right hand; F: left hand (hold F to raise a shield); X swaps hands; Q throws. Esc: walk away "
            "or the menu. H: ask the device.")


def device_context(state: dict, question: str) -> dict:
    """What the device can know: what the stranger carries, wears and has seen, what they tried, the story step
    (with its written hints as guidance), and the controls. Never anyone's secrets or anything unseen."""
    here = minds.player_cell(state)
    player = state["player"]
    in_sight = [n for n in state["npcs"] if math.dist(minds._cell(n), here) <= minds.SIGHT_CELLS]
    things = [o for o in state["objects"].values() if o.get("holder_id") is None and "carry" in o["capabilities"]
              and math.dist((o["x"], o["y"]), here) <= minds.SIGHT_CELLS]
    attempts = [e for e in state.get("journal", []) if e.get("kind") == "craft"][-3:]
    current = step(state)
    return {
        "question": question,
        "tutorial": bool(current),
        "step": {"title": current["title"], "objective": current.get("task", ""),
                 "hints_you_may_give": current.get("help", []),
                 **({"words_suggested": current["suggest"]["text"]} if current.get("suggest") else {})}
        if current else None,
        "goal": "Get inside the city (the gate to the north is shut to strangers)",
        "you_carry": [{"name": o["name"], "what_it_is": gear.words(o)} for o in carried(state)],
        "you_wear": sorted({state["objects"][oid]["name"] for slot, oid in (player.get("equipped") or {}).items()
                            if slot in gear.COVERS and oid in state["objects"]}),
        "your_health": round(float(player.get("health", 100))),
        "your_wounds": [gear.describe(c) for c in player.get("conditions", []) if c["kind"] != "knocked_out"],
        "people_in_sight": [{"name": n["name"], "role": minds.card(n).get("role", ""),
                             "state": "dead" if not n.get("alive", True) else "down" if n.get("down") else
                             "hurt" if n.get("health", 100) < 100 else "well"} for n in in_sight],
        "things_in_sight": [o["name"] for o in things][:20],
        "recent_attempts": [{"tried": e.get("text", ""), "result": e.get("category", ""),
                             "why": e.get("reason", "")[:200]} for e in attempts],
        "controls": CONTROLS,
    }


def fallback_answer(state: dict) -> str:
    """When the model can't be asked: the current step's first hint, or the controls."""
    current = step(state)
    if current and current.get("help"):
        return current["help"][0]
    return "I can't reach far right now. Look around, talk to people, and try what you know. H asks me again."
