"""Try Something: what the judge sees, what code allows, and the committed effects.

Models propose; this module decides what a proposal may change (GDD section 6.2).
Each validator decision is recorded as a note so the developer trace shows why.
Actions: make an object, take items, transform (cut, break, fell) one thing, harm a person.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections import deque
from pathlib import Path

import m2

ROOT = Path(__file__).resolve().parents[1]
CONTENT = json.loads((ROOT / "data" / "content" / "materials.json").read_text(encoding="utf-8"))
MAX_EFFORT_SECONDS = 14_400  # Felling a large tree by hand can take hours.
MAX_PIECES = 8
MAX_STEPS = 4
PRIOR_RULINGS = 10
PEOPLE_RADIUS = 8.0  # Cells within which the judge is told about people.
WITNESS_RADIUS = 10.0  # Cells within which people are recorded as witnesses (reactions come in M4).
WOUND_DAMAGE = 45
DISABLED_HEALTH = 20  # Down and out of the fight, but alive (D-41).
NEARBY_WALK_STEPS = 14  # Things this many steps away can be acted on; the player walks there first.
WALK_CELLS_PER_SECOND = 7.1875  # Matches the backend walking speed.
THROW_RANGE = 8.0  # Cells.
MAX_THROW_KG = 5.0
# Flags describing an active state need an input that can cause it. Without one the
# flag becomes an untested capability instead of a physical fact.
ACTIVE_FLAGS = {
    "magnetized": ({"magnet_source", "magnetized"}, "might become magnetic if touched to a real magnet"),
    "magnet_source": ({"magnet_source", "magnetized"}, "might attract iron if it were magnetic"),
    "light_source": ({"light_source", "heat_source"}, "could give light if lit"),
    "heat_source": ({"heat_source"}, "could give heat if lit"),
}
OPERATION_CAPABILITIES = {"tieable": "tie", "container": "fill"}


def _names(state: dict) -> dict[str, str]:
    return {npc["id"]: npc["name"] for npc in state["npcs"]}


def owner_label(state: dict, obj: dict) -> str:
    owner = obj["owner_id"]
    return "nobody" if owner is None else "you" if owner == "player" else _names(state).get(owner, owner)


def _distance(state: dict, x: int, y: int) -> float:
    return math.dist((state["player"]["x"], state["player"]["y"]), (x, y))


def _blocked_cells(state: dict) -> set[tuple[int, int]]:
    cleared = cleared_obstacles(state)
    return {(cx, cy) for item in m2._GEOMETRY["buildings"] + m2._GEOMETRY["obstacles"] if item["name"] not in cleared
            for bx, by, w, h in [item["cells"]] for cx in range(bx, bx + w) for cy in range(by, by + h)}


def _walkable(cell: tuple[int, int], blocked: set) -> bool:
    return 0 <= cell[0] < 96 and 9 <= cell[1] < 72 and cell not in blocked


def _bfs(start: tuple[int, int], blocked: set, limit: int) -> tuple[dict, dict]:
    previous, steps = {start: None}, {start: 0}
    frontier = deque([start])
    while frontier:
        cell = frontier.popleft()
        if steps[cell] >= limit:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt not in previous and _walkable(nxt, blocked):
                previous[nxt], steps[nxt] = cell, steps[cell] + 1
                frontier.append(nxt)
    return previous, steps


def _path_to_reach(start: tuple[int, int], target: tuple[int, int], blocked: set,
                   limit: int = NEARBY_WALK_STEPS) -> list[list[int]] | None:
    """Shortest walk from start to any cell within reach of target; [] if already within reach."""
    if math.dist(start, target) <= m2.REACH_CELLS:
        return []
    previous, steps = _bfs(start, blocked, limit)
    goals = [c for c in steps if math.dist(c, target) <= m2.REACH_CELLS]
    if not goals:
        return None
    cell = min(goals, key=lambda c: (steps[c], math.dist(c, target), c))
    path = []
    while cell != start:
        path.append([cell[0], cell[1]])
        cell = previous[cell]
    return path[::-1]


def walk_costs(state: dict) -> dict[str, int]:
    """Steps the player must walk to be within reach of each loose object and person nearby."""
    start = (state["player"]["x"], state["player"]["y"])
    _, steps = _bfs(start, _blocked_cells(state), NEARBY_WALK_STEPS)

    def cost(x: int, y: int) -> int | None:
        options = [n for cell, n in steps.items() if math.dist(cell, (x, y)) <= m2.REACH_CELLS]
        return min(options) if options else None
    costs = {}
    for obj in state["objects"].values():
        if obj["holder_id"] == "player":
            costs[obj["id"]] = 0
        elif obj["holder_id"] is None and math.dist(start, (obj["x"], obj["y"])) <= NEARBY_WALK_STEPS + 3:
            found = cost(obj["x"], obj["y"])
            if found is not None:
                costs[obj["id"]] = found
    for npc in state["npcs"]:
        if math.dist(start, (npc["x"], npc["y"])) <= NEARBY_WALK_STEPS + 3:
            found = cost(npc["x"], npc["y"])
            if found is not None:
                costs[npc["id"]] = found
    return costs


def available_items(state: dict, costs: dict | None = None) -> list[dict]:
    """Carried items plus anything intact the player can walk to nearby, whoever owns it."""
    costs = walk_costs(state) if costs is None else costs
    return [obj for obj in state["objects"].values()
            if obj["id"] in costs and obj["holder_id"] in (None, "player")
            and "water_source" not in obj["capabilities"] and obj["condition"] == "usable"]


def people_nearby(state: dict, costs: dict | None = None) -> list[dict]:
    costs = walk_costs(state) if costs is None else costs
    people = []
    for npc in state["npcs"]:
        distance = _distance(state, npc["x"], npc["y"])
        if distance <= PEOPLE_RADIUS:
            health = npc.get("health", 100)
            people.append({
                "id": npc["id"], "name": npc["name"], "role": npc["role"], "distance_cells": round(distance, 1),
                "within_reach": distance <= m2.REACH_CELLS, "walk_steps": costs.get(npc["id"]),
                "condition": ("dead" if not npc.get("alive", True) else "down (disabled, can't fight)"
                              if npc.get("down") else "unhurt" if health >= 100
                              else "wounded" if health > 30 else "badly wounded (near death)"),
                "injuries": npc.get("injuries", []),
                "armour": minds_card(npc).get("armor_text", "no armour"),
                "weapon": minds_card(npc).get("weapon") or "none",
                "aware_of_you": _aware(state, npc),
                "activity": (npc.get("controller") or {}).get("activity", "standing")})
    return people


def minds_card(npc: dict) -> dict:
    import minds  # minds imports crafting
    return minds.card(npc)


def _aware(state: dict, npc: dict) -> bool:
    """Is this person watching the stranger (facing them, busy with them, or fighting them)? If not, they can
    be taken by surprise."""
    my_mind = npc.get("mind") or {}
    return bool(my_mind.get("facing_player") or my_mind.get("job") and my_mind["job"].get("target") == "player"
                or npc["id"] in ((state.get("fight") or {}).get("attackers") or []))


# The armour law (D-41): what can't get through mail, whatever anyone says. Everything else is judged.
SOFT_MATERIALS = {"wood", "bone", "flint", "stone", "grass", "fibre", "fiber", "reed", "clay", "leather", "cloth",
                  "rope", "straw", "bark"}
HEAVY_KG = 3.0  # A heavy blow (a sledge, a big rock) can still hurt through mail by weight alone.


def _stopped_by_mail(state: dict, npc: dict, method: str, weapon: dict | None) -> bool:
    if minds_card(npc).get("armor") != "mail" or method == "poured":
        return False
    if weapon is None:
        return True  # Fists and feet against mail.
    materials = {m.lower() for m in weapon.get("materials", [])}
    return materials <= SOFT_MATERIALS and weapon.get("mass_kg", 0) < HEAVY_KG


def _judge_view(state: dict, obj: dict, costs: dict) -> dict:
    return {"id": obj["id"], "name": obj["name"], "kind": obj.get("feature", "item"),
            "walk_steps": costs.get(obj["id"], 0),
            "distance_cells": 0 if obj["holder_id"] == "player" else round(_distance(state, obj["x"], obj["y"]), 1),
            "description": obj.get("description", ""), "materials": obj.get("materials", []),
            "mass_kg": obj["mass_kg"], "length_m": obj.get("length_m"), "flags": obj.get("flags", []),
            "carried_by_player": obj["holder_id"] == "player", "portable": "carry" in obj["capabilities"],
            "belongs_to": owner_label(state, obj) + (" (lent to the player)" if obj.get("lent_to") == "player" else ""),
            **({"capacity_l": obj["capacity_l"], "water_l": obj.get("water_l", 0.0)} if obj.get("capacity_l") else {}),
            **({"temperature": obj["temperature"]} if obj.get("temperature", "cold") != "cold" else {}),
            **({"burning": True} if obj.get("burning") else {}),
            **({"known_capabilities": obj["known_capabilities"]} if obj.get("known_capabilities") else {})}


def water_sources(state: dict, costs: dict) -> list[dict]:
    return [{"id": o["id"], "name": o["name"], "water_l": o["water_l"], "walk_steps": costs[o["id"]],
             "belongs_to": owner_label(state, o)}
            for o in state["objects"].values() if "water_source" in o["capabilities"] and o["id"] in costs]


def prior_rulings(state: dict) -> list[dict]:
    rulings = [{"intention": e["text"], "action": e.get("action", "make"), "outcome": e["category"],
                "reason": e["reason"], "made": e.get("made_name"), "precedent_key": e.get("precedent_key")}
               for e in state["journal"] if e.get("kind") == "craft" and e["category"] != "unresolved"]
    return rulings[-PRIOR_RULINGS:]


def build_context(state: dict, text: str, selected_ids: list[str]) -> dict:
    costs = walk_costs(state)
    items = available_items(state, costs)
    people = people_nearby(state, costs)
    known = {o["id"] for o in items} | {p["id"] for p in people}
    return {"player_intention": text,
            "highlighted_ids": [i for i in selected_ids if i in known],
            "player_cell": [state["player"]["x"], state["player"]["y"]],
            "available_items": [_judge_view(state, o, costs) for o in items],
            "water_sources": water_sources(state, costs),
            "people_nearby": people,
            "prior_rulings": prior_rulings(state)}


def _verdict(category: str, reason: str, notes: list[str], effort: int = 0, **extra) -> dict:
    base = {"category": category, "reason": reason, "effort_seconds": effort, "notes": notes, "action": "other",
            "consumed_ids": [], "tool_ids": [], "new_spec": None, "take_ids": [], "transform": None,
            "harm": None, "fill": None, "demonstration": None, "give": None, "install": None, "offer_trade": None,
            "drop_ids": [],
            "property": [], "precedent_key": None,
            "walk": []}
    base.update(extra)
    return base


def _unresolved(notes: list[str], note: str) -> dict:
    return _verdict("unresolved", "The attempt could not be resolved. Nothing changed.", notes + [f"Rejected: {note}"])


def _dedupe(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _material_matches(material: str, inputs: set[str]) -> str | None:
    """Loose match so 'grass' fits 'dry grass'; returns the canonical input material."""
    if material in inputs:
        return material
    return next((m for m in sorted(inputs) if material in m or m in material), None)


def _checked_materials(proposed: list[str], allowed: set[str], notes: list[str]) -> list[str]:
    materials: list[str] = []
    for material in (m.lower().strip() for m in proposed):
        match = _material_matches(material, allowed)
        if match is None:
            notes.append(f"Stripped material '{material}': nothing it came from is made of it.")
        elif match not in materials:
            materials.append(match)
    if not materials:
        materials = sorted(allowed)
        notes.append(f"Materials set from the inputs: {materials}.")
    return materials


def _checked_flags(proposed: list[str], materials: list[str], support: set[str], capabilities: list[dict],
                   notes: list[str]) -> list[str]:
    flags: list[str] = []
    for flag in _dedupe(proposed):
        causes = ACTIVE_FLAGS.get(flag)
        if causes and not causes[0] & support:
            notes.append(f"Stripped flag '{flag}': no input can cause it. Recorded as untested.")
            capabilities.append({"text": causes[1], "status": "untested"})
        elif flag == "ferromagnetic" and "iron" not in materials:
            notes.append("Stripped flag 'ferromagnetic': it contains no iron.")
        else:
            flags.append(flag)
    return flags


def _positive(value) -> float | None:
    return round(float(value), 3) if value is not None and float(value) > 0 else None


def _property(state: dict, ids: list[str], how: str) -> list[dict]:
    return [{"id": i, "name": state["objects"][i]["name"], "owner_id": state["objects"][i]["owner_id"], "how": how}
            for i in ids if state["objects"][i]["owner_id"] not in (None, "player")
            and state["objects"][i].get("lent_to") != "player"]  # Lent by its owner: theirs, but not theft.


def validate(state: dict, judged: dict | None, service_error: str | None = None) -> dict:
    """Turn a judge proposal into what code will actually commit, against the current state."""
    notes: list[str] = []
    if judged is None:
        return _verdict("unresolved", service_error or "The judge could not be reached. Nothing changed.", notes)
    action = judged.get("action", "make")
    outcome, reason = judged["outcome"], judged["reason"].strip() or "Nothing happens."
    effort = max(0, min(MAX_EFFORT_SECONDS, int(judged["effort_seconds"])))
    key = judged.get("precedent_key")
    proposed_change = any(judged.get(field) for field in ("new_object", "take_ids", "transformation", "harm", "fill", "change",
                                                          "demonstration", "give", "install", "offer_trade"))
    if outcome != "success" and proposed_change:
        notes.append(f"Ignored proposed changes because outcome is '{outcome}'.")
    if outcome == "needs_clarification":
        return _verdict(outcome, judged.get("clarifying_question") or reason, notes, action=action, precedent_key=key)
    if outcome in ("blocked", "unsupported"):
        if effort:
            notes.append(f"Effort {effort}s ignored: '{outcome}' spends no time.")
        return _verdict(outcome, reason, notes, action=action, precedent_key=key)
    if outcome == "failed":
        return _verdict("failed", reason, notes, max(1, effort), action=action, precedent_key=key)
    available = {o["id"]: o for o in available_items(state)}
    if effort < 1 and action != "other":
        notes.append("Effort raised to 1 s: doing something takes time.")
    effort = max(1, effort) if action != "other" else effort
    handlers = {"make": _make, "take": _take, "transform": _transform, "harm": _harm, "fill": _fill, "change": _change,
                "demonstrate": _demonstrate, "give": _give, "install": _install, "offer_trade": _offer_trade,
                "drop": _drop}
    if action not in handlers:
        return _verdict("success", reason, notes, effort, action="other", precedent_key=key)
    # Things further than arm's reach are reached by walking there first.
    walk = _plan_walk(state, _walk_targets(state, action, judged, available))
    if walk is None:
        return _verdict("blocked", "That's too far away to get to from here.",
                        notes + ["Blocked by code: no walkable path within range."], action=action,
                        precedent_key=key)
    probe = state
    if walk:
        probe = dict(state)
        probe["player"] = {**state["player"], "x": walk[-1][0], "y": walk[-1][1]}
        seconds = math.ceil(len(walk) / WALK_CELLS_PER_SECOND)
        effort += seconds
        notes.append(f"Walked {len(walk)} cells first ({seconds} s).")
    verdict = handlers[action](probe, judged, available, notes, reason, effort, key)
    if verdict["category"] == "success":
        verdict["walk"] = walk
    return verdict


def _walk_targets(state: dict, action: str, judged: dict, available: dict) -> list[tuple[int, int]]:
    """Cells the player must be within reach of for this step, in no particular order."""
    ids: list[str] = []
    plan = judged.get("new_object") or {}
    if action == "make":
        ids = plan.get("consumes", []) + plan.get("tools_used", [])
    elif action == "take":
        ids = judged.get("take_ids") or []
    elif action == "transform" and judged.get("transformation"):
        ids = [judged["transformation"]["target_id"]] + judged["transformation"]["tools_used"]
    elif action == "fill" and judged.get("fill"):
        ids = [judged["fill"]["container_id"]]
    elif action == "install" and judged.get("install"):
        ids = [judged["install"]["object_id"], judged["install"]["into_id"]] + judged["install"]["aid_ids"]
    elif action == "demonstrate" and judged.get("demonstration"):
        ids = [judged["demonstration"]["object_id"]] + judged["demonstration"]["used_ids"]
    harm = judged.get("harm") if action == "harm" else None
    if harm and harm.get("method", "melee") != "thrown" and harm.get("weapon_id"):
        ids = [harm["weapon_id"]]
    cells = [(available[i]["x"], available[i]["y"]) for i in _dedupe(ids)
             if i in available and available[i]["holder_id"] != "player"]
    source = state["objects"].get((judged.get("fill") or {}).get("source_id") or "") if action == "fill" else None
    if source is not None:
        cells.append((source["x"], source["y"]))
    if action == "demonstrate":  # Showing something in a trough or other water source: go to it.
        cells += [(o["x"], o["y"]) for i in ids if (o := state["objects"].get(i)) and "water_source" in o["capabilities"]]
    recipient = (judged.get("give") or {}).get("recipient_id") if action == "give" else \
        (judged.get("offer_trade") or {}).get("recipient_id") if action == "offer_trade" else None
    npc = next((n for n in state["npcs"] if n["id"] == recipient), None) if recipient else None
    if npc is not None:
        cells.append((npc["x"], npc["y"]))
    if harm and harm.get("method", "melee") != "thrown":
        npc = next((n for n in state["npcs"] if n["id"] == harm["target_id"]), None)
        if npc is not None:
            cells.append((npc["x"], npc["y"]))
    return cells


def _plan_walk(state: dict, targets: list[tuple[int, int]]) -> list[list[int]] | None:
    """Visit each target nearest-first; None if one cannot be reached."""
    if not targets:
        return []
    blocked = _blocked_cells(state)
    position = (state["player"]["x"], state["player"]["y"])
    path: list[list[int]] = []
    remaining = list(dict.fromkeys(targets))
    while remaining:
        options = [(route, target) for target in remaining
                   if (route := _path_to_reach(position, target, blocked, NEARBY_WALK_STEPS * 2)) is not None]
        if not options:
            return None
        route, target = min(options, key=lambda option: len(option[0]))
        path += route
        position = tuple(route[-1]) if route else position
        remaining.remove(target)
    return path


def _make(state, judged, available, notes, reason, effort, key) -> dict:
    spec = judged.get("new_object")
    if not spec:
        return _unresolved(notes, "action 'make' without a new_object")
    consumes = _dedupe(spec["consumes"])
    tools = [i for i in _dedupe(spec["tools_used"]) if i not in consumes]
    missing = [i for i in consumes + tools if i not in available]
    if missing:
        return _unresolved(notes, f"proposal used items that are not available now: {missing}")
    if not consumes:
        return _unresolved(notes, "a new object must be made from at least one consumed item")
    fixed = [i for i in consumes if "carry" not in available[i]["capabilities"]]
    if fixed:
        return _unresolved(notes, f"{fixed} cannot be built into an object without being cut up first")
    for item_id in consumes:
        partners = set(state["objects"][item_id]["bound_to"]) | {
            o["id"] for o in state["objects"].values() if item_id in o["bound_to"]}
        if not partners <= set(consumes):
            return _unresolved(notes, f"{item_id} is tied to {sorted(partners - set(consumes))}, "
                                      "which is not part of the new object")
    input_materials = {m.lower() for i in consumes for m in available[i].get("materials", [])}
    materials = _checked_materials(spec["materials"], input_materials, notes)
    input_mass = round(sum(available[i]["mass_kg"] for i in consumes), 3)
    mass = float(spec["mass_kg"])
    if not 0 < mass <= input_mass:
        clamped = max(0.01, min(mass, input_mass))
        notes.append(f"Mass {mass} kg clamped to {clamped} kg (consumed items weigh {input_mass} kg).")
        mass = clamped
    capabilities = [dict(c) for c in spec["capabilities"]]
    support = {f for i in consumes + tools for f in available[i].get("flags", [])
               if f not in ("heat_source", "light_source") or available[i].get("burning")}
    if can_kindle([available[i] for i in consumes + tools]):  # Sparks into tinder: a real way to make fire.
        support |= {"heat_source", "light_source"}
    flags = _checked_flags(spec["flags"], materials, support, capabilities, notes)
    capacity = spec.get("capacity_l")
    if capacity and "container" not in flags:
        notes.append("Dropped capacity_l: the object is not flagged as a container.")
        capacity = None
    new_spec = {"name": spec["name"].strip().lower()[:60] or "made thing",
                "description": spec["description"].strip()[:400], "materials": materials,
                "mass_kg": round(mass, 3), "length_m": _positive(spec.get("length_m")),
                "capacity_l": _positive(capacity), "rated_load_kg": _positive(spec.get("rated_load_kg")),
                "flags": flags, "known_capabilities": capabilities[:6],
                **({"burning": True} if "heat_source" in flags else {})}  # Made alight: a fire.
    tools_not_ours = [i for i in tools if available[i]["holder_id"] != "player"]
    return _verdict("success", reason, notes, effort, action="make", consumed_ids=consumes, tool_ids=tools,
                    new_spec=new_spec, precedent_key=key,
                    property=_property(state, consumes, "used up") + _property(state, tools_not_ours, "used"))


def can_kindle(things: list[dict]) -> bool:
    """Something already burning, or flint and iron to strike sparks with dry tinder to catch them."""
    if any(t.get("burning") for t in things):
        return True
    flint = any("flint" in " ".join(t.get("materials", [])).lower() or "flint" in t["name"] for t in things)
    iron = any("ferromagnetic" in t.get("flags", []) or "iron" in t.get("materials", []) or
               "steel" in t.get("materials", []) for t in things)
    tinder = any("combustible" in t.get("flags", []) and t["mass_kg"] <= 1.0 for t in things)
    return flint and iron and tinder


HEAT_ORDER = ["cold", "warm", "hot", "boiling"]
COOLING_MS = {"boiling": 120_000, "hot": 300_000, "warm": 600_000}  # How long each lasts off the fire.
FIRE_MS_PER_KG = 600_000  # A made fire burns about ten minutes per kilogram of fuel...
FIRE_MS_RANGE = (120_000, 1_800_000)  # ...between two and thirty minutes.


def display_name(obj: dict) -> str:
    """The name follows the state: "clay bowl", "clay bowl of water", "clay bowl of boiling water"."""
    base = obj.get("base_name") or obj["name"]
    heat = obj.get("temperature", "cold")
    if obj.get("capacity_l") and obj.get("water_l", 0) > 0 and "water_source" not in obj.get("capabilities", []):
        return f"{base} of {'' if heat == 'cold' else heat + ' '}water"
    if obj.get("burning") and obj.get("feature") != "fire":
        return f"burning {base}"
    if heat in ("hot", "boiling") and not obj.get("capacity_l"):
        return f"hot {base}"
    return base


def rename(obj: dict) -> None:
    obj.setdefault("base_name", obj["name"])
    obj["name"] = display_name(obj)


def age_objects(state: dict, elapsed_ms: int, now: int) -> dict[str, dict]:
    """Time passing for things (by code, no model): hot things cool back, fires burn down.
    Returns {object_id: changed fields} for the event payload."""
    changes: dict[str, dict] = {}
    end = now + elapsed_ms
    for obj in state.get("objects", {}).values():
        fields = {}
        heat = obj.get("temperature", "cold")
        if heat != "cold" and obj.get("heated_at") is not None:
            level, since = heat, obj["heated_at"]
            while level != "cold" and end - since >= COOLING_MS[level]:
                since += COOLING_MS[level]
                level = HEAT_ORDER[HEAT_ORDER.index(level) - 1]
            if level != heat:
                fields.update(temperature=level, heated_at=None if level == "cold" else since)
        if obj.get("burning") and obj.get("burns_until") is not None and end >= obj["burns_until"]:
            fields.update(burning=False, burns_until=None,
                          flags=[f for f in obj.get("flags", []) if f not in ("heat_source", "light_source")])
            if obj.get("feature") == "fire" or obj.get("created_by") == "player" and not obj.get("capacity_l"):
                fields.update(condition="burnt out", description=f"The cold ashes of what was a {obj['name']}.")
        if fields:
            probe = {**obj, **fields}
            probe.setdefault("base_name", obj["name"])
            fields.update(base_name=probe["base_name"], name=display_name(probe))
            changes[obj["id"]] = fields
    return changes


def _change(state, judged, available, notes, reason, effort, key) -> dict:
    """A thing changes in place (heat, cool, set alight, put out, pour). The judge says what; code keeps the laws:
    heat and flame only from something really burning within reach, water conserved, time enough to boil."""
    plan = judged.get("change")
    if not plan:
        return _unresolved(notes, "action 'change' without a change")
    target = available.get(plan["target_id"])
    if target is None:
        return _unresolved(notes, f"the thing to change is not within reach: {plan['target_id']}")
    fields: dict = {}
    source = available.get(plan.get("heat_source_id") or "") or state["objects"].get(plan.get("heat_source_id") or "")
    lit = source is not None and source.get("burning") and _distance(state, source["x"], source["y"]) <= m2.REACH_CELLS + 1
    temperature = plan.get("temperature")
    if temperature and HEAT_ORDER.index(temperature) > HEAT_ORDER.index(target.get("temperature", "cold")):
        if not lit:
            return _verdict("blocked", f"There's nothing burning here to heat the {target['name']} with.",
                            notes + ["Blocked by code: heat needs something burning within reach."],
                            action="change", precedent_key=key)
        needed = 60 + int(240 * max(0.2, target.get("water_l", 0.0))) if temperature == "boiling" else 30
        if effort < needed:
            notes.append(f"Effort raised to {needed} s: water takes time to heat.")
            effort = needed
    if temperature:
        fields.update(temperature=temperature, heated_at=state["sim_time_ms"] + effort * 1000
                      if temperature != "cold" else None)
    if plan.get("burning") is True and not target.get("burning"):
        if not lit:
            return _verdict("blocked", f"You have no flame to light the {target['name']} with.",
                            notes + ["Blocked by code: nothing burning within reach."], action="change",
                            precedent_key=key)
        if "combustible" not in target.get("flags", []):
            return _verdict("failed", f"The {target['name']} won't catch fire.", notes, max(1, effort),
                            action="change", precedent_key=key)
        span = max(FIRE_MS_RANGE[0], min(FIRE_MS_RANGE[1], int(target["mass_kg"] * FIRE_MS_PER_KG)))
        fields.update(burning=True, burns_until=state["sim_time_ms"] + effort * 1000 + span,
                      flags=_dedupe(target.get("flags", []) + ["heat_source", "light_source"]))
    elif plan.get("burning") is False and target.get("burning"):
        fields.update(burning=False, burns_until=None,
                      flags=[f for f in target.get("flags", []) if f not in ("heat_source", "light_source")])
    pour = []
    litres = float(plan.get("pour_litres") or 0.0)
    if litres > 0:
        held = target.get("water_l", 0.0)
        litres = round(min(litres, held), 3)
        into = available.get(plan.get("pour_into_id") or "")
        if into is not None:
            room = round((into.get("capacity_l") or 0.0) - into.get("water_l", 0.0), 3)
            litres = min(litres, max(0.0, room))
            pour.append({"id": into["id"], "water_l": round(into.get("water_l", 0.0) + litres, 3),
                         "temperature": target.get("temperature", "cold"), "heated_at": target.get("heated_at")})
        fields["water_l"] = round(held - litres, 3)
    if not fields and not pour:
        return _verdict("success", reason, notes, effort, action="other", precedent_key=key)
    return _verdict("success", reason, notes, effort, action="change", precedent_key=key,
                    change={"id": target["id"], "fields": fields, "pour": pour,
                            "spilled_l": round(litres, 3) if litres > 0 and not pour else 0.0},
                    property=_property(state, [target["id"]], "used"))


def quick(state: dict, verb: str, object_id: str) -> dict:
    """A judge-shaped proposal for the deterministic quick actions (E to pick up, Put down): no model involved."""
    obj = state["objects"].get(object_id)
    if obj is None:
        return {"clarifying_question": None, "precedent_key": f"quick:{verb}", "steps": [{
            "action": "other", "outcome": "blocked", "reason": "There's nothing like that here.", "effort_seconds": 0,
            "new_object": None, "take_ids": [], "transformation": None, "harm": None}]}
    step = {"action": verb, "outcome": "success", "effort_seconds": 2, "new_object": None, "transformation": None,
            "harm": None, "take_ids": [object_id] if verb == "take" else [], "drop_ids": [object_id] if verb == "drop" else [],
            "reason": f"You pick up the {obj['name']}." if verb == "take" else f"You put down the {obj['name']}."}
    return {"clarifying_question": None, "precedent_key": f"quick:{verb}", "steps": [step]}


def _drop(state, judged, available, notes, reason, effort, key) -> dict:
    ids = [i for i in _dedupe(judged.get("drop_ids") or []) if state["objects"].get(i, {}).get("holder_id") == "player"]
    if not ids:
        return _verdict("blocked", "You aren't carrying that.", notes, action="drop", precedent_key=key)
    return _verdict("success", reason, notes, effort, action="drop", precedent_key=key, drop_ids=ids)


def _take(state, judged, available, notes, reason, effort, key) -> dict:
    ids = _dedupe(judged.get("take_ids") or [])
    if not ids:
        return _unresolved(notes, "action 'take' without take_ids")
    missing = [i for i in ids if i not in available]
    if missing:
        return _unresolved(notes, f"cannot take items that are not within reach: {missing}")
    carried = [i for i in ids if available[i]["holder_id"] == "player"]
    ids = [i for i in ids if i not in carried]
    if carried:
        notes.append(f"Already carried, skipped: {carried}.")
    if not ids:
        return _verdict("blocked", "You are already carrying that.", notes, action="take", precedent_key=key)
    fixed = [available[i]["name"] for i in ids if "carry" not in available[i]["capabilities"]]
    if fixed:
        return _verdict("blocked", f"The {fixed[0]} can't be picked up and carried.", notes + [
            f"Blocked by code: not portable {fixed}."], action="take", precedent_key=key)
    load = m2.inventory_mass(state) + sum(available[i]["mass_kg"] + available[i]["water_l"] for i in ids)
    if load > m2.CARRY_LIMIT_KG:
        return _verdict("blocked", f"That would be more than you can carry ({load:.1f} of "
                                   f"{m2.CARRY_LIMIT_KG:.0f} kg).", notes, action="take", precedent_key=key)
    return _verdict("success", reason, notes, effort, action="take", take_ids=ids, precedent_key=key,
                    property=_property(state, ids, "taken"))


def _transform(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("transformation")
    if not plan:
        return _unresolved(notes, "action 'transform' without a transformation")
    target_id = plan["target_id"]
    if target_id not in available:
        return _unresolved(notes, f"transform target is not within reach: {target_id}")
    target = available[target_id]
    if state["objects"][target_id]["bound_to"] or any(target_id in o["bound_to"] for o in state["objects"].values()):
        return _unresolved(notes, f"{target_id} is tied to something; untie it first")
    tools = [i for i in _dedupe(plan["tools_used"]) if i != target_id]
    missing = [i for i in tools if i not in available]
    if missing:
        return _unresolved(notes, f"transform used tools that are not available now: {missing}")
    target_materials = {m.lower() for m in target.get("materials", [])}
    support = {f for i in [target_id] + tools for f in available[i].get("flags", [])}
    pieces, total = [], 0
    for piece in plan["pieces"]:
        count = max(1, int(piece["count"]))
        if total + count > MAX_PIECES:
            notes.append(f"Piece '{piece['name']}' count cut from {count} to {MAX_PIECES - total} (max {MAX_PIECES}).")
            count = MAX_PIECES - total
        if count <= 0:
            continue
        total += count
        capabilities = [dict(c) for c in piece["capabilities"]]
        materials = _checked_materials(piece["materials"], target_materials, notes)
        pieces.append({"name": piece["name"].strip().lower()[:60] or "piece",
                       "description": piece["description"].strip()[:400], "materials": materials,
                       "count": count, "mass_kg": max(0.01, float(piece["mass_kg"])),
                       "length_m": _positive(piece.get("length_m")),
                       "flags": _checked_flags(piece["flags"], materials, support, capabilities, notes),
                       "known_capabilities": capabilities[:4]})
    if not pieces:
        return _unresolved(notes, "transform produced no pieces")
    produced = sum(p["mass_kg"] * p["count"] for p in pieces)
    if produced > target["mass_kg"]:
        scale = target["mass_kg"] / produced
        for piece in pieces:
            piece["mass_kg"] = round(piece["mass_kg"] * scale, 3)
        notes.append(f"Piece masses scaled by {scale:.2f}: they weighed {produced:.1f} kg, "
                     f"more than the {target['mass_kg']} kg {target['name']}.")
    transform = {"target_id": target_id, "result_state": plan["result_state"], "pieces": pieces}
    tools_not_ours = [i for i in tools if available[i]["holder_id"] != "player"]
    return _verdict("success", reason, notes, effort, action="transform", tool_ids=tools, transform=transform,
                    precedent_key=key,
                    property=_property(state, [target_id], plan["result_state"]) +
                    _property(state, tools_not_ours, "used"))


def _harm(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("harm")
    if not plan:
        return _unresolved(notes, "action 'harm' without a harm")
    npc = next((n for n in state["npcs"] if n["id"] == plan["target_id"]), None)
    if npc is None:
        return _unresolved(notes, f"harm target is not a person: {plan['target_id']}")
    if not npc.get("alive", True):
        return _verdict("blocked", f"{npc['name']} is already dead.", notes, action="harm", precedent_key=key)
    if npc.get("down") and plan["result"] == "disabled":
        plan = {**plan, "result": "wounded"}  # Already down: another blow can only wound or kill.
    method = plan.get("method", "melee")
    weapon = plan.get("weapon_id")
    if weapon is not None and weapon not in available:
        return _unresolved(notes, f"weapon is not at hand: {weapon}")
    result = plan["result"]
    if method == "poured" and weapon is None:  # Unnamed, but only one thing in hand holds water: that one.
        held = [o["id"] for o in available.values() if o["holder_id"] == "player" and o.get("water_l", 0) > 0]
        if len(held) == 1:
            weapon = held[0]
            notes.append(f"Poured from {weapon}, the only thing in hand holding water.")
    if method == "poured":  # A law: only what's really hot can scald; cold water only soaks.
        container = available.get(weapon) if weapon else None
        if container is None or container.get("water_l", 0) <= 0:
            return _verdict("blocked", "There's nothing in your hands to pour.", notes, action="harm", precedent_key=key)
        if container.get("temperature", "cold") in ("cold", "warm") and result != "missed":
            notes.append(f"Law: {container.get('temperature', 'cold')} water can't wound; result set to missed.")
            result = "missed"
            reason = f"The water only soaks {npc['name']}."
    if result not in ("missed", "deflected") and _stopped_by_mail(state, npc, method, available.get(weapon) if weapon else None):
        thing = available[weapon]["name"] if weapon else "bare hands"
        notes.append(f"Law: {thing} can't get through {npc['name']}'s mail; result set to deflected.")
        result = "deflected"
        reason = f"The blow glances off {npc['name']}'s mail."
    distance = _distance(state, npc["x"], npc["y"])
    picked_up = []
    if method == "thrown":
        thrown = available.get(weapon) if weapon else None
        if thrown is None or thrown["holder_id"] != "player":
            return _verdict("blocked", "You need to be holding something to throw it.", notes, action="harm",
                            precedent_key=key)
        if "carry" not in thrown["capabilities"] or thrown["mass_kg"] > MAX_THROW_KG:
            return _verdict("blocked", f"The {thrown['name']} is too heavy to throw.", notes, action="harm",
                            precedent_key=key)
        if distance > THROW_RANGE:
            return _verdict("blocked", f"{npc['name']} is too far away to throw at.",
                            notes + [f"Blocked by code: target {distance:.1f} cells away (throw range "
                                     f"{THROW_RANGE:.0f})."], action="harm", precedent_key=key)
    else:
        if distance > m2.REACH_CELLS:
            return _verdict("blocked", f"{npc['name']} is too far away to reach.",
                            notes + [f"Blocked by code: target {distance:.1f} cells away (reach {m2.REACH_CELLS})."],
                            action="harm", precedent_key=key)
        if weapon is not None and available[weapon]["holder_id"] != "player":
            if "carry" not in available[weapon]["capabilities"]:
                return _verdict("blocked", f"You can't wield the {available[weapon]['name']}.", notes,
                                action="harm", precedent_key=key)
            picked_up = [weapon]  # Picked up on the way.
    witnesses = [n["id"] for n in state["npcs"] if n["id"] != npc["id"] and n.get("alive", True)
                 and _distance(state, n["x"], n["y"]) <= WITNESS_RADIUS]
    harm = {"target_id": npc["id"], "weapon_id": weapon, "method": method, "result": result,
            "injury": plan["injury"].strip()[:200] if result not in ("missed", "deflected") else "soaked but unhurt"
            if method == "poured" else plan["injury"].strip()[:200], "witnesses": witnesses}
    return _verdict("success", reason, notes, effort, action="harm", harm=harm, precedent_key=key,
                    take_ids=picked_up, property=_property(state, picked_up, "taken"))


def _fill(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("fill")
    if not plan:
        return _unresolved(notes, "action 'fill' without a fill")
    container, source = available.get(plan["container_id"]), state["objects"].get(plan["source_id"])
    if container is None:
        return _unresolved(notes, f"container is not within reach: {plan['container_id']}")
    if source is None or "water_source" not in source["capabilities"]:
        return _unresolved(notes, f"not a water source: {plan['source_id']}")
    if "container" not in container.get("flags", []) or not container.get("capacity_l"):
        return _verdict("blocked", f"The {container['name']} can't hold water.", notes, action="fill",
                        precedent_key=key)
    if _distance(state, source["x"], source["y"]) > m2.REACH_CELLS:
        return _verdict("blocked", f"The {source['name']} is too far away.", notes, action="fill", precedent_key=key)
    room = round(container["capacity_l"] - container.get("water_l", 0.0), 3)
    if room <= 0:
        return _verdict("blocked", f"The {container['name']} is already full.", notes, action="fill", precedent_key=key)
    if source["water_l"] <= 0:
        return _verdict("blocked", f"The {source['name']} is empty.", notes, action="fill", precedent_key=key)
    requested = float(plan["litres"]) if float(plan["litres"]) > 0 else room
    litres = round(min(requested, room, source["water_l"]), 3)
    if litres < requested:
        notes.append(f"Filled {litres} L, not {requested} L: limited by space or the water available.")
    if container["holder_id"] == "player" and m2.inventory_mass(state) + litres > m2.CARRY_LIMIT_KG:
        return _verdict("blocked", "That much water would be more than you can carry.", notes, action="fill",
                        precedent_key=key)
    return _verdict("success", reason, notes, effort, action="fill", precedent_key=key,
                    fill={"container_id": container["id"], "source_id": source["id"], "litres": litres},
                    property=_property(state, [container["id"], source["id"]], "used"))


def _demonstrate(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("demonstration")
    if not plan:
        return _unresolved(notes, "action 'demonstrate' without a demonstration")
    ids = _dedupe([plan["object_id"]] + list(plan["used_ids"]))
    water = [i for i in ids[1:] if "water_source" in state["objects"].get(i, {}).get("capabilities", [])]
    missing = [i for i in ids if i not in available and i not in water]
    if missing:
        return _unresolved(notes, f"can only show things that are at hand: {missing}")
    far = [state["objects"][i]["name"] for i in water
           if _distance(state, state["objects"][i]["x"], state["objects"][i]["y"]) > m2.REACH_CELLS]
    if far:
        return _verdict("blocked", f"The {far[0]} is too far away.", notes, action="demonstrate", precedent_key=key)
    shown = available[plan["object_id"]]
    living = {n["id"] for n in state["npcs"] if n.get("alive", True)}
    results = [{"text": " ".join(r["text"].split())[:120], "status": r["status"]} for r in plan["capabilities"][:4]
               if r["text"].strip() and r["status"] in ("observed", "failed")]
    demonstration = {"object_id": shown["id"], "object_name": shown["name"], "used_ids": ids[1:],
                     "audience_ids": [i for i in _dedupe(plan["audience_ids"]) if i in living],
                     "observed": " ".join(plan["observed"].split())[:300] or f"The stranger showed a {shown['name']}.",
                     "works": bool(plan["works"]), "results": results}
    not_ours = [i for i in ids if i in water or available[i]["holder_id"] != "player"]
    return _verdict("success", reason, notes, effort, action="demonstrate", demonstration=demonstration,
                    precedent_key=key, property=_property(state, not_ours, "used"))


def _give(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("give")
    if not plan:
        return _unresolved(notes, "action 'give' without a give")
    npc = next((n for n in state["npcs"] if n["id"] == plan["recipient_id"]), None)
    if npc is None:
        return _unresolved(notes, f"give recipient is not a person: {plan['recipient_id']}")
    if not npc.get("alive", True):
        return _verdict("blocked", f"{npc['name']} is dead.", notes, action="give", precedent_key=key)
    ids = _dedupe(plan["item_ids"])
    loose = [i for i in ids if state["objects"].get(i, {}).get("holder_id") != "player"]
    if not ids or loose:
        name = state["objects"].get(loose[0], {}).get("name", "that") if loose else "anything"
        return _verdict("blocked", f"You aren't carrying {'the ' + name if loose else name} to give.",
                        notes, action="give", precedent_key=key)
    if _distance(state, npc["x"], npc["y"]) > m2.REACH_CELLS:
        return _verdict("blocked", f"{npc['name']} is too far away to hand anything to.", notes, action="give",
                        precedent_key=key)
    others = [i for i in ids if state["objects"][i]["owner_id"] not in (None, "player", npc["id"])]
    return _verdict("success", reason, notes, effort, action="give", precedent_key=key,
                    give={"item_ids": ids, "recipient_id": npc["id"], "recipient_name": npc["name"],
                          "names": [state["objects"][i]["name"] + (
                              f" with {state['objects'][i]['water_l']:g} L of water in it"
                              if state["objects"][i].get("water_l") else "") for i in ids]},
                    property=_property(state, others, "given away"))


def _install(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("install")
    if not plan:
        return _unresolved(notes, "action 'install' without an install")
    obj, into = available.get(plan["object_id"]), available.get(plan["into_id"])
    if obj is None or into is None:
        return _unresolved(notes, f"install needs the object and the fixture at hand: {plan['object_id']}, {plan['into_id']}")
    if into.get("feature") != "fixture":
        return _verdict("blocked", f"The {obj['name']} can't be fitted into the {into['name']}.", notes,
                        action="install", precedent_key=key)
    if obj.get("installed_in"):
        return _verdict("blocked", f"The {obj['name']} is already in place.", notes, action="install", precedent_key=key)
    aids = [i for i in _dedupe(plan["aid_ids"]) if i not in (obj["id"], into["id"])]
    missing = [i for i in aids if i not in available]
    if missing:
        return _unresolved(notes, f"aids that are not at hand: {missing}")
    if obj["mass_kg"] > m2.CARRY_LIMIT_KG and not aids:
        return _verdict("blocked", f"The {obj['name']} is far too heavy to lift into place by hand.",
                        notes + ["Blocked by code: heavier than one person can lift, and no aids."],
                        action="install", precedent_key=key)
    install = {"object_id": obj["id"], "object_name": obj["name"], "into_id": into["id"], "into_name": into["name"],
               "aid_ids": aids, "aid_names": [available[i]["name"] for i in aids]}
    # Putting something where it belongs isn't taking it; borrowing someone's tools to do it is.
    not_ours = [i for i in aids if available[i]["holder_id"] != "player"]
    return _verdict("success", reason, notes, effort, action="install", install=install, precedent_key=key,
                    property=_property(state, not_ours, "used"))


def _offer_trade(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("offer_trade")
    if not plan:
        return _unresolved(notes, "action 'offer_trade' without an offer_trade")
    npc = next((n for n in state["npcs"] if n["id"] == plan["recipient_id"]), None)
    if npc is None:
        return _unresolved(notes, f"trade partner is not a person: {plan['recipient_id']}")
    if not npc.get("alive", True):
        return _verdict("blocked", f"{npc['name']} is dead.", notes, action="offer_trade", precedent_key=key)
    give, want = _dedupe(plan["give_ids"]), _dedupe(plan["want_ids"])
    mine = [i for i in give if (o := state["objects"].get(i)) and o["holder_id"] == "player"
            and o["owner_id"] in (None, "player")]
    if not give or len(mine) != len(give):
        return _verdict("blocked", "You can only trade things that are yours and in your hands.", notes,
                        action="offer_trade", precedent_key=key)
    theirs = [i for i in want if (o := state["objects"].get(i)) and o["owner_id"] == npc["id"]
              and o["holder_id"] in (None, npc["id"]) and "carry" in o["capabilities"]]
    if not want or len(theirs) != len(want):
        return _unresolved(notes, f"can only ask for {npc['name']}'s own portable things: {want}")
    if _distance(state, npc["x"], npc["y"]) > 5:
        return _verdict("blocked", f"{npc['name']} is too far away to bargain with.", notes, action="offer_trade",
                        precedent_key=key)
    offer = {"recipient_id": npc["id"], "recipient_name": npc["name"], "give_ids": give, "want_ids": want,
             "give_names": [state["objects"][i]["name"] for i in give],
             "want_names": [state["objects"][i]["name"] for i in want]}
    return _verdict("success", reason, notes, effort, action="offer_trade", offer_trade=offer, precedent_key=key)


def _known_after(obj: dict, results: list[dict], event_id: int) -> list[dict]:
    """The object's capabilities with what a demonstration showed: matching ones updated, new ones added."""
    known = [dict(c) for c in obj.get("known_capabilities", [])]
    for result in results:
        match = next((c for c in known if c["text"].casefold() == result["text"].casefold()), None)
        if match is None:
            if len(known) >= 6:
                continue
            match = {"text": result["text"]}
            known.append(match)
        match.update(status=result["status"], event_id=event_id)
    return known


def placeholder_category(materials: list[str]) -> str:
    categories = CONTENT["placeholder_categories"]
    return next((categories[m] for m in materials if m in categories), "bundle")


def cleared_obstacles(state: dict) -> set[str]:
    """Geometry obstacles removed by play, such as felled trees."""
    return {o["geometry_name"] for o in state["objects"].values()
            if o.get("geometry_name") and o["condition"] != "usable"}


def _open_cells_near(state: dict, x: int, y: int, cleared: set[str], count: int) -> list[tuple[int, int]]:
    """Nearest open cells around (x, y), preferring ones without loose objects, for dropping pieces."""
    blocked = {(cx, cy) for item in m2._GEOMETRY["buildings"] + m2._GEOMETRY["obstacles"]
               if item["name"] not in cleared
               for bx, by, w, h in [item["cells"]] for cx in range(bx, bx + w) for cy in range(by, by + h)}
    occupied = {(o["x"], o["y"]) for o in state["objects"].values() if o["holder_id"] is None}
    ring = sorted(((dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)), key=lambda d: (math.hypot(*d), d))
    cells = [(x + dx, y + dy) for dx, dy in ring
             if 0 <= x + dx < 96 and 9 <= y + dy < 72 and (x + dx, y + dy) not in blocked]
    free = [c for c in cells if c not in occupied] + [c for c in cells if c in occupied]
    return [free[i % len(free)] for i in range(count)] if free else [(x, y)] * count


def _object(new_id: str, run_id: str, spec: dict, x: int, y: int, owner, holder, text: str, event_id: int,
            components: list[str], tools: list[str], asset_id: str | None = None) -> dict:
    portable = spec["mass_kg"] <= m2.CARRY_LIMIT_KG
    caps = (["carry"] + [op for flag, op in OPERATION_CAPABILITIES.items() if flag in spec["flags"]]
            if portable else [])
    return {"id": new_id, "name": spec["name"], "description": spec["description"], "x": x, "y": y,
            "mass_kg": spec["mass_kg"], "owner_id": owner, "holder_id": holder if portable else None,
            "capabilities": caps, "bound_to": [], "water_l": 0.0, "capacity_l": spec.get("capacity_l") or 0.0,
            "condition": "usable", "materials": spec["materials"], "flags": spec["flags"],
            "length_m": spec.get("length_m"), "rated_load_kg": spec.get("rated_load_kg"),
            "known_capabilities": spec["known_capabilities"], "components": components, "tools_used": tools,
            "created_by": "player", "created_event_id": event_id, "created_text": text,
            "sprite_asset_id": asset_id or f"spr_{run_id[:8]}_{new_id}",
            "placeholder": placeholder_category(spec["materials"])}


def _step_deltas(state: dict, run_id: str, text: str, verdict: dict, event_id: int, number: int) -> dict:
    """World changes for one validated step; ids stay unique across the steps of one attempt."""
    suffix = "" if number == 1 else f"_{number}"
    walk = verdict.get("walk") or []
    px, py = walk[-1] if walk else (state["player"]["x"], state["player"]["y"])
    new_objects, consumed, taken, transformed, npc_updates, moved = [], [], [], None, [], []
    water, known, given, spilled, installed, trade = [], None, None, 0.0, None, None
    if verdict["action"] == "make":
        spec = verdict["new_spec"]
        consumed = verdict["consumed_ids"]
        carried_consumed = sum(state["objects"][i]["mass_kg"] + state["objects"][i]["water_l"]
                               for i in consumed if state["objects"][i]["holder_id"] == "player")
        fits = m2.inventory_mass(state) - carried_consumed + spec["mass_kg"] <= m2.CARRY_LIMIT_KG
        if not fits:
            verdict["notes"].append("Too heavy to carry with the current load; left at the player's feet.")
        new_objects.append(_object(f"made_{event_id}{suffix}", run_id, spec, px, py, "player",
                                   "player" if fits else None, text, event_id, consumed, verdict["tool_ids"]))
        if spec.get("burning"):  # A fire: it stays where it was lit and burns down with its fuel.
            span = max(FIRE_MS_RANGE[0], min(FIRE_MS_RANGE[1], int(spec["mass_kg"] * FIRE_MS_PER_KG)))
            new_objects[-1].update(burning=True, feature="fire", capabilities=[], holder_id=None,
                                   burns_until=state["sim_time_ms"] + verdict["effort_seconds"] * 1000 + span)
        # Water in anything built in stays in the new thing if it holds water; otherwise it spills.
        held = round(sum(state["objects"][i].get("water_l", 0.0) for i in consumed), 3)
        kept = min(held, spec.get("capacity_l") or 0.0) if "container" in spec["flags"] else 0.0
        new_objects[-1]["water_l"] = kept
        spilled = round(held - kept, 3)
    elif verdict["action"] == "take":
        taken = verdict["take_ids"]
    elif verdict["action"] == "drop":
        moved = [{"id": i, "x": px, "y": py} for i in verdict["drop_ids"]]  # At the stranger's feet.
    elif verdict["action"] == "transform":
        plan = verdict["transform"]
        target = state["objects"][plan["target_id"]]
        cleared = cleared_obstacles(state) | ({target["geometry_name"]} if target.get("geometry_name") else set())
        in_hand = target["holder_id"] == "player"
        load = m2.inventory_mass(state) - (target["mass_kg"] if in_hand else 0)
        total = sum(p["count"] for p in plan["pieces"])
        cells = iter(_open_cells_near(state, px if in_hand else target["x"], py if in_hand else target["y"],
                                      cleared, total))
        index = 0
        for piece in plan["pieces"]:
            asset_id = None
            for _ in range(piece["count"]):
                index += 1
                keep = in_hand and load + piece["mass_kg"] <= m2.CARRY_LIMIT_KG
                load += piece["mass_kg"] if keep else 0
                x, y = next(cells)
                obj = _object(f"piece_{event_id}{suffix}_{index}", run_id, piece, x, y,
                              "player" if target["owner_id"] == "player" else target["owner_id"],
                              "player" if keep else None, text, event_id, [plan["target_id"]],
                              verdict["tool_ids"], asset_id)
                asset_id = obj["sprite_asset_id"]  # Identical pieces share one painting.
                new_objects.append(obj)
        transformed = {"id": plan["target_id"], "result_state": plan["result_state"],
                       "into": [o["id"] for o in new_objects]}
    elif verdict["action"] == "harm":
        harm = verdict["harm"]
        npc = next(n for n in state["npcs"] if n["id"] == harm["target_id"])
        health = npc.get("health", 100)
        down = bool(npc.get("down"))
        if harm["result"] == "killed":
            health = 0
        elif harm["result"] == "disabled":  # Out of the fight, alive: scalded blind, stunned, a leg gone from under them.
            health, down = min(health, DISABLED_HEALTH), True
        elif harm["result"] == "wounded":
            health = max(0, health - WOUND_DAMAGE)
            if health == 0:
                # Wounds add up: say so, rather than reporting a wound and quietly killing.
                harm["result"] = "killed"
                verdict["reason"] = verdict["reason"].rstrip() + f" {npc['name']} does not survive this wound."
                verdict["notes"].append("Wound was fatal: the injuries added up (health reached 0).")
        injuries = npc.get("injuries", []) + ([harm["injury"]] if harm["result"] not in ("missed", "deflected") else [])
        npc_updates.append({"id": npc["id"], "alive": health > 0, "health": health, "injuries": injuries,
                            **({"down": True} if down and health > 0 else {})})
        taken = verdict["take_ids"]  # A weapon picked up on the way.
        if harm["method"] == "thrown" and harm["weapon_id"]:
            x, y = _open_cells_near(state, npc["x"], npc["y"], cleared_obstacles(state), 1)[0]
            moved.append({"id": harm["weapon_id"], "x": x, "y": y})
        if harm["method"] == "poured" and harm["weapon_id"]:  # Emptied over them.
            spilled = state["objects"][harm["weapon_id"]].get("water_l", 0.0)
            water = [{"id": harm["weapon_id"], "water_l": 0.0, "temperature": "cold", "heated_at": None}]
    elif verdict["action"] == "fill":
        fill = verdict["fill"]
        container, source = state["objects"][fill["container_id"]], state["objects"][fill["source_id"]]
        water = [{"id": container["id"], "water_l": round(container.get("water_l", 0.0) + fill["litres"], 3)},
                 {"id": source["id"], "water_l": round(source["water_l"] - fill["litres"], 3)}]
    elif verdict["action"] == "change":
        change = verdict["change"]
        water = [{"id": change["id"], **change["fields"]}] + change["pour"]
        spilled = change["spilled_l"]
    elif verdict["action"] == "demonstrate":
        shown = verdict["demonstration"]
        known = {"id": shown["object_id"],
                 "known_capabilities": _known_after(state["objects"][shown["object_id"]], shown["results"], event_id)}
    elif verdict["action"] == "install":
        plan = verdict["install"]
        into = state["objects"][plan["into_id"]]
        installed = {"id": plan["object_id"], "into": plan["into_id"], "x": into["x"], "y": into["y"]}
    elif verdict["action"] == "offer_trade":
        trade = {**verdict["offer_trade"], "id": f"trade_{event_id}{suffix}", "status": "offered",
                 "offered_event": event_id}
    elif verdict["action"] == "give":
        give = verdict["give"]
        # A gift of your own (or unowned) thing makes it theirs; someone else's thing stays theirs.
        given = {"ids": give["item_ids"], "to": give["recipient_id"],
                 "owners": {i: give["recipient_id"] if state["objects"][i]["owner_id"] in (None, "player")
                            else state["objects"][i]["owner_id"] for i in give["item_ids"]}}
    deltas = {"consumed_ids": consumed, "new_objects": new_objects, "taken_ids": taken, "transformed": transformed,
              "npc_updates": npc_updates, "moved": moved, "walk": walk,
              "player_to": [px, py] if walk else None}
    deltas.update({k: v for k, v in (("water", water), ("capabilities", known), ("given", given),
                                     ("spilled_l", spilled), ("installed", installed), ("trade", trade)) if v})
    return deltas


def _apply_step(state: dict, deltas: dict) -> None:
    if deltas.get("player_to"):
        state["player"].update(x=deltas["player_to"][0], y=deltas["player_to"][1])
    for landed in deltas.get("moved", []):
        state["objects"][landed["id"]].update(x=landed["x"], y=landed["y"], holder_id=None)
    new_objects = deltas.get("new_objects") or ([deltas["new_object"]] if deltas.get("new_object") else [])
    if new_objects:
        for item_id in deltas["consumed_ids"]:
            # Its water went into the new thing (or spilled): see _step_deltas.
            state["objects"][item_id].update(holder_id=f"in:{new_objects[0]['id']}", water_l=0.0)
        for obj in new_objects:
            state["objects"][obj["id"]] = obj
            rename(obj)
    for item_id in deltas.get("taken_ids", []):
        state["objects"][item_id]["holder_id"] = "player"
    for change in deltas.get("water", []):  # Water moved, heated, poured; any change of state in place.
        state["objects"][change["id"]].update({k: v for k, v in change.items() if k != "id"})
        if not state["objects"][change["id"]].get("water_l"):
            state["objects"][change["id"]].update(temperature=state["objects"][change["id"]].get("temperature", "cold")
                                                  if not state["objects"][change["id"]].get("capacity_l") else "cold")
        rename(state["objects"][change["id"]])
    if deltas.get("spilled_l"):
        state["water_spilled_l"] = round(state.get("water_spilled_l", 0.0) + deltas["spilled_l"], 3)
    if deltas.get("capabilities"):
        state["objects"][deltas["capabilities"]["id"]]["known_capabilities"] = deltas["capabilities"]["known_capabilities"]
    if deltas.get("installed"):
        placed = deltas["installed"]
        state["objects"][placed["id"]].update(installed_in=placed["into"], x=placed["x"], y=placed["y"],
                                              holder_id=None, condition="installed")
    if deltas.get("trade"):
        state.setdefault("trades", {})[deltas["trade"]["id"]] = dict(deltas["trade"])
    given = deltas.get("given")
    for item_id in (given or {}).get("ids", []):
        state["objects"][item_id].update(holder_id=given["to"], owner_id=given["owners"][item_id])
    transformed = deltas.get("transformed")
    if transformed:
        target = state["objects"][transformed["id"]]
        target.update(condition=transformed["result_state"], holder_id=f"into:{transformed['into'][0]}",
                      became=transformed["into"])
    for update in deltas.get("npc_updates", []):
        npc = next(n for n in state["npcs"] if n["id"] == update["id"])
        npc.update(alive=update["alive"], health=update["health"])
        if "injuries" in update:
            npc["injuries"] = list(update["injuries"])
        elif update.get("injury"):  # Seed-5 payloads before multi-step recorded one injury at a time.
            npc.setdefault("injuries", []).append(update["injury"])
        if not update["alive"] and npc.get("controller"):
            npc["controller"].update(activity="dead", path=[], source="dead")
        elif update.get("down") and not npc.get("down"):
            npc["down"] = True
            if npc.get("mind"):
                npc["mind"]["job"] = None
            if npc.get("controller"):
                npc["controller"].update(activity="down", path=[], source="down")


_REFERENCE = re.compile(r"^made_by_step_(\d+)$")


def _resolve_references(step: dict, made_by_step: dict[int, str]) -> dict:
    """Point 'made_by_step_N' at the object that step actually made."""
    def swap(value):
        match = _REFERENCE.match(value) if isinstance(value, str) else None
        return made_by_step.get(int(match.group(1)), value) if match else value
    step = copy.deepcopy(step)
    if step.get("new_object"):
        step["new_object"]["consumes"] = [swap(i) for i in step["new_object"]["consumes"]]
        step["new_object"]["tools_used"] = [swap(i) for i in step["new_object"]["tools_used"]]
    step["take_ids"] = [swap(i) for i in step.get("take_ids") or []]
    if step.get("transformation"):
        step["transformation"]["target_id"] = swap(step["transformation"]["target_id"])
        step["transformation"]["tools_used"] = [swap(i) for i in step["transformation"]["tools_used"]]
    if step.get("harm"):
        step["harm"]["weapon_id"] = swap(step["harm"]["weapon_id"])
    return step


def humanize(text: str, state: dict, made_by_step: dict[int, str]) -> str:
    """Replace any id that leaked into player-facing text with the thing's name."""
    names = {oid: ("the ", o["name"]) for oid, o in state["objects"].items()}
    names.update({f"made_by_step_{n}": ("the ", state["objects"][oid]["name"]) for n, oid in made_by_step.items()})
    names.update({n["id"]: ("", n["name"]) for n in state["npcs"]})
    pattern = re.compile(r"\b(the |your |a |an )?(" + "|".join(
        re.escape(key) for key in sorted(names, key=len, reverse=True)) + r")\b")

    def swap(match):
        article = match.group(1)
        default, name = names[match.group(2)]
        return ((article or default) if default else "") + name
    return pattern.sub(swap, text)


def resolve_attempt(state: dict, run_id: str, text: str, judged: dict | None, service_error: str | None,
                    trace_id: str, now_ms: int) -> tuple[dict, dict, dict]:
    """Validate and apply the judge's steps in order on a draft world; stop at the first that fails.

    Returns (event payload, summary verdict for the trace, draft state after the committed steps).
    """
    event_id = state["event_seq"] + 1
    draft = copy.deepcopy(state)
    verdicts, deltas, made_by_step = [], [], {}
    if judged is None:
        verdicts.append(validate(draft, None, service_error))
    elif judged.get("clarifying_question"):
        verdicts.append(_verdict("needs_clarification", judged["clarifying_question"], []))
    elif not judged.get("steps"):
        verdicts.append(_unresolved([], "the judge returned no steps"))
    else:
        for number, step in enumerate(judged["steps"][:MAX_STEPS], 1):
            verdict = validate(draft, _resolve_references(step, made_by_step))
            verdicts.append(verdict)
            if verdict["category"] != "success":
                break
            step_deltas = _step_deltas(draft, run_id, text, verdict, event_id, number)
            _apply_step(draft, step_deltas)
            deltas.append(step_deltas)
            if step_deltas["new_objects"]:
                made_by_step[number] = step_deltas["new_objects"][0]["id"]
        if len(judged["steps"]) > MAX_STEPS and verdicts[-1]["category"] == "success":
            verdicts[-1]["notes"].append(f"Only the first {MAX_STEPS} steps were attempted.")
    for verdict in verdicts:
        verdict["reason"] = humanize(verdict["reason"], draft, made_by_step)
    committed = [v for v in verdicts if v["category"] == "success"]
    last = verdicts[-1]
    category = "success" if last["category"] == "success" else "partial_success" if committed else last["category"]
    made_ids = [o["id"] for d in deltas for o in d["new_objects"]]
    crafted = next((d["new_objects"][0]["id"] for d, v in zip(deltas, committed) if v["action"] == "make"), None)
    harm = next((v["harm"] for v in reversed(committed) if v["harm"]), None)
    summary = {
        "category": category, "action": last["action"],
        "reason": " ".join(v["reason"] for v in verdicts),
        "effort_seconds": sum(v["effort_seconds"] for v in verdicts),
        "notes": [n for v in verdicts for n in v["notes"]] if len(verdicts) == 1 else
                 [f"Step {i}: {n}" for i, v in enumerate(verdicts, 1) for n in v["notes"]],
        "consumed_ids": [i for v in committed for i in v["consumed_ids"]],
        "tool_ids": [i for v in committed for i in v["tool_ids"]],
        "new_spec": next((v["new_spec"] for v in committed if v["new_spec"]), None),
        "take_ids": [i for v in committed for i in v["take_ids"]],
        "transform": next((v["transform"] for v in reversed(committed) if v["transform"]), None),
        "harm": harm, "property": [c for v in committed for c in v["property"]],
        "fill": next((v["fill"] for v in reversed(committed) if v["fill"]), None),
        "demonstration": next((v["demonstration"] for v in reversed(committed) if v["demonstration"]), None),
        "give": next((v["give"] for v in reversed(committed) if v["give"]), None),
        "install": next((v["install"] for v in reversed(committed) if v["install"]), None),
        "offer_trade": next((v["offer_trade"] for v in reversed(committed) if v["offer_trade"]), None),
        "precedent_key": (judged or {}).get("precedent_key"),
        "steps": [{"action": v["action"], "category": v["category"], "reason": v["reason"], "notes": v["notes"]}
                  for v in verdicts]}
    transformed = next((d["transformed"] for d in reversed(deltas) if d["transformed"]), None)
    px, py = state["player"]["x"], state["player"]["y"]
    entry = {"kind": "craft", "action": summary["action"], "text": text, "category": category,
             "reason": summary["reason"], "steps": summary["steps"],
             "step": {"step_id": "step_1", "operation_key": "craft", "actor_id": "player",
                      "input_refs": [{"existing_entity_id": i} for i in summary["consumed_ids"] +
                                     summary["tool_ids"] + summary["take_ids"] +
                                     ([transformed["id"]] if transformed else [])],
                      "output_bindings": made_ids, "depends_on": [], "required_capabilities": [],
                      "required_skill": None, "effort_seconds": summary["effort_seconds"], "risk_tags": [],
                      "status": "completed" if category == "success" else category},
             "player_cell": [px, py], "event_id": event_id,
             "made": crafted or (made_ids[0] if made_ids else None), "crafted": crafted,
             "made_name": draft["objects"][crafted or made_ids[0]]["name"] if made_ids else None,
             "made_ids": made_ids, "taken_ids": summary["take_ids"], "transformed": transformed, "harm": harm,
             "fill": summary["fill"], "demonstration": summary["demonstration"], "give": summary["give"],
             "install": summary["install"], "offer_trade": summary["offer_trade"],
             "walk": [cell for d in deltas for cell in d.get("walk", [])],
             "property": summary["property"], "precedent_key": summary["precedent_key"], "trace_id": trace_id}
    payload = {"steps": deltas, "journal_entry": entry, "sim_time_ms": now_ms + summary["effort_seconds"] * 1000}
    return payload, summary, draft


def apply_payload(state: dict, payload: dict) -> None:
    # People first, so wounds and deaths recorded by the steps are applied on top of their movement.
    if "npcs" in payload:
        state["npcs"] = payload["npcs"]
    for deltas in payload["steps"] if "steps" in payload else [payload]:  # Older events are one step.
        _apply_step(state, deltas)
    state["journal"].append(payload["journal_entry"])
    state["last_action"] = payload["journal_entry"]
    state["sim_time_ms"] = payload["sim_time_ms"]
