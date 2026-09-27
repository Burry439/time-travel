"""Try Something: what the judge sees, what code allows, and the committed effects.

Models propose; this module decides what a proposal may change (GDD section 6.2).
Each validator decision is recorded as a note so the developer trace shows why.
Actions: make an object, take items, transform (cut, break, fell) one thing, harm a person.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import m2

ROOT = Path(__file__).resolve().parents[1]
CONTENT = json.loads((ROOT / "data" / "content" / "materials.json").read_text(encoding="utf-8"))
MAX_EFFORT_SECONDS = 14_400  # Felling a large tree by hand can take hours.
MAX_PIECES = 8
PRIOR_RULINGS = 10
PEOPLE_RADIUS = 8.0  # Cells within which the judge is told about people.
WITNESS_RADIUS = 10.0  # Cells within which people are recorded as witnesses (reactions come in M4).
WOUND_DAMAGE = 45
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


def available_items(state: dict) -> list[dict]:
    """Carried items plus anything intact within reach, whoever owns it."""
    return [obj for obj in state["objects"].values()
            if (obj["holder_id"] == "player" or (obj["holder_id"] is None and m2.accessible(state, obj)))
            and "water_source" not in obj["capabilities"] and obj["condition"] == "usable"]


def people_nearby(state: dict) -> list[dict]:
    people = []
    for npc in state["npcs"]:
        distance = _distance(state, npc["x"], npc["y"])
        if distance <= PEOPLE_RADIUS:
            health = npc.get("health", 100)
            people.append({
                "id": npc["id"], "name": npc["name"], "role": npc["role"], "distance_cells": round(distance, 1),
                "within_reach": distance <= m2.REACH_CELLS,
                "condition": "dead" if not npc.get("alive", True) else "wounded" if health < 100 else "unhurt",
                "activity": (npc.get("controller") or {}).get("activity", "standing")})
    return people


def _judge_view(state: dict, obj: dict) -> dict:
    return {"id": obj["id"], "name": obj["name"], "kind": obj.get("feature", "item"),
            "description": obj.get("description", ""), "materials": obj.get("materials", []),
            "mass_kg": obj["mass_kg"], "length_m": obj.get("length_m"), "flags": obj.get("flags", []),
            "carried_by_player": obj["holder_id"] == "player", "portable": "carry" in obj["capabilities"],
            "belongs_to": owner_label(state, obj)}


def prior_rulings(state: dict) -> list[dict]:
    rulings = [{"intention": e["text"], "action": e.get("action", "make"), "outcome": e["category"],
                "reason": e["reason"], "made": e.get("made_name"), "precedent_key": e.get("precedent_key")}
               for e in state["journal"] if e.get("kind") == "craft" and e["category"] != "unresolved"]
    return rulings[-PRIOR_RULINGS:]


def build_context(state: dict, text: str, selected_ids: list[str]) -> dict:
    items = available_items(state)
    people = people_nearby(state)
    known = {o["id"] for o in items} | {p["id"] for p in people}
    return {"player_intention": text,
            "highlighted_ids": [i for i in selected_ids if i in known],
            "player_cell": [state["player"]["x"], state["player"]["y"]],
            "available_items": [_judge_view(state, o) for o in items],
            "people_nearby": people,
            "prior_rulings": prior_rulings(state)}


def _verdict(category: str, reason: str, notes: list[str], effort: int = 0, **extra) -> dict:
    base = {"category": category, "reason": reason, "effort_seconds": effort, "notes": notes, "action": "other",
            "consumed_ids": [], "tool_ids": [], "new_spec": None, "take_ids": [], "transform": None,
            "harm": None, "property": [], "precedent_key": None}
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
            for i in ids if state["objects"][i]["owner_id"] not in (None, "player")]


def validate(state: dict, judged: dict | None, service_error: str | None = None) -> dict:
    """Turn a judge proposal into what code will actually commit, against the current state."""
    notes: list[str] = []
    if judged is None:
        return _verdict("unresolved", service_error or "The judge could not be reached. Nothing changed.", notes)
    action = judged.get("action", "make")
    outcome, reason = judged["outcome"], judged["reason"].strip() or "Nothing happens."
    effort = max(0, min(MAX_EFFORT_SECONDS, int(judged["effort_seconds"])))
    key = judged.get("precedent_key")
    proposed_change = any(judged.get(field) for field in ("new_object", "take_ids", "transformation", "harm"))
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
    handlers = {"make": _make, "take": _take, "transform": _transform, "harm": _harm}
    if action not in handlers:
        return _verdict("success", reason, notes, effort, action="other", precedent_key=key)
    return handlers[action](state, judged, available, notes, reason, effort, key)


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
    support = {f for i in consumes + tools for f in available[i].get("flags", [])}
    flags = _checked_flags(spec["flags"], materials, support, capabilities, notes)
    capacity = spec.get("capacity_l")
    if capacity and "container" not in flags:
        notes.append("Dropped capacity_l: the object is not flagged as a container.")
        capacity = None
    new_spec = {"name": spec["name"].strip().lower()[:60] or "made thing",
                "description": spec["description"].strip()[:400], "materials": materials,
                "mass_kg": round(mass, 3), "length_m": _positive(spec.get("length_m")),
                "capacity_l": _positive(capacity), "rated_load_kg": _positive(spec.get("rated_load_kg")),
                "flags": flags, "known_capabilities": capabilities[:6]}
    tools_not_ours = [i for i in tools if available[i]["holder_id"] != "player"]
    return _verdict("success", reason, notes, effort, action="make", consumed_ids=consumes, tool_ids=tools,
                    new_spec=new_spec, precedent_key=key,
                    property=_property(state, consumes, "used up") + _property(state, tools_not_ours, "used"))


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
    distance = _distance(state, npc["x"], npc["y"])
    if distance > m2.REACH_CELLS:
        return _verdict("blocked", f"{npc['name']} is too far away to reach.",
                        notes + [f"Blocked by code: target {distance:.1f} cells away (reach {m2.REACH_CELLS})."],
                        action="harm", precedent_key=key)
    weapon = plan.get("weapon_id")
    if weapon is not None and weapon not in available:
        return _unresolved(notes, f"weapon is not at hand: {weapon}")
    witnesses = [n["id"] for n in state["npcs"] if n["id"] != npc["id"] and n.get("alive", True)
                 and _distance(state, n["x"], n["y"]) <= WITNESS_RADIUS]
    harm = {"target_id": npc["id"], "weapon_id": weapon, "result": plan["result"],
            "injury": plan["injury"].strip()[:200], "witnesses": witnesses}
    return _verdict("success", reason, notes, effort, action="harm", harm=harm, precedent_key=key)


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


def build_payload(state: dict, run_id: str, text: str, verdict: dict, trace_id: str,
                  sim_time_ms: int) -> dict:
    """Event payload holding only deltas; apply_payload replays it."""
    event_id = state["event_seq"] + 1
    px, py = state["player"]["x"], state["player"]["y"]
    new_objects, consumed, taken, transformed, npc_updates, harm = [], [], [], None, [], None
    if verdict["category"] == "success" and verdict["action"] == "make":
        spec = verdict["new_spec"]
        consumed = verdict["consumed_ids"]
        carried_consumed = sum(state["objects"][i]["mass_kg"] + state["objects"][i]["water_l"]
                               for i in consumed if state["objects"][i]["holder_id"] == "player")
        fits = m2.inventory_mass(state) - carried_consumed + spec["mass_kg"] <= m2.CARRY_LIMIT_KG
        if not fits:
            verdict["notes"].append("Too heavy to carry with the current load; left at the player's feet.")
        new_objects.append(_object(f"made_{event_id}", run_id, spec, px, py, "player", "player" if fits else None,
                                   text, event_id, consumed, verdict["tool_ids"]))
    elif verdict["category"] == "success" and verdict["action"] == "take":
        taken = verdict["take_ids"]
    elif verdict["category"] == "success" and verdict["action"] == "transform":
        plan = verdict["transform"]
        target = state["objects"][plan["target_id"]]
        cleared = cleared_obstacles(state) | ({target["geometry_name"]} if target.get("geometry_name") else set())
        in_hand = target["holder_id"] == "player"
        load = m2.inventory_mass(state) - (target["mass_kg"] if in_hand else 0)
        total = sum(p["count"] for p in plan["pieces"])
        cells = iter(_open_cells_near(state, target["x"] if not in_hand else px,
                                      target["y"] if not in_hand else py, cleared, total))
        index = 0
        for piece in plan["pieces"]:
            asset_id = None
            for _ in range(piece["count"]):
                index += 1
                new_id = f"piece_{event_id}_{index}"
                keep = in_hand and load + piece["mass_kg"] <= m2.CARRY_LIMIT_KG
                load += piece["mass_kg"] if keep else 0
                x, y = next(cells)
                obj = _object(new_id, run_id, piece, x, y, target["owner_id"] if target["owner_id"] != "player"
                              else "player", "player" if keep else None, text, event_id, [plan["target_id"]],
                              verdict["tool_ids"], asset_id)
                asset_id = obj["sprite_asset_id"]  # Identical pieces share one painting.
                new_objects.append(obj)
        transformed = {"id": plan["target_id"], "result_state": plan["result_state"],
                       "into": [o["id"] for o in new_objects]}
    elif verdict["category"] == "success" and verdict["action"] == "harm":
        harm = verdict["harm"]
        npc = next(n for n in state["npcs"] if n["id"] == harm["target_id"])
        health = npc.get("health", 100)
        if harm["result"] == "killed":
            health = 0
        elif harm["result"] == "wounded":
            health = max(0, health - WOUND_DAMAGE)
        npc_updates.append({"id": npc["id"], "alive": health > 0, "health": health,
                            "injury": harm["injury"] if harm["result"] != "missed" else None})
    made = new_objects
    entry = {"kind": "craft", "action": verdict["action"], "text": text, "category": verdict["category"],
             "reason": verdict["reason"],
             "step": {"step_id": "step_1", "operation_key": "craft", "actor_id": "player",
                      "input_refs": [{"existing_entity_id": i} for i in
                                     consumed + verdict["tool_ids"] + taken +
                                     ([transformed["id"]] if transformed else [])],
                      "output_bindings": [o["id"] for o in made], "depends_on": [], "required_capabilities": [],
                      "required_skill": None, "effort_seconds": verdict["effort_seconds"], "risk_tags": [],
                      "status": "completed" if verdict["category"] == "success" else verdict["category"]},
             "player_cell": [px, py], "event_id": event_id,
             "made": made[0]["id"] if made else None, "made_name": made[0]["name"] if made else None,
             "made_ids": [o["id"] for o in made], "taken_ids": taken, "transformed": transformed,
             "harm": harm, "property": verdict["property"],
             "precedent_key": verdict["precedent_key"], "trace_id": trace_id}
    return {"consumed_ids": consumed, "new_objects": new_objects, "taken_ids": taken, "transformed": transformed,
            "npc_updates": npc_updates, "journal_entry": entry, "sim_time_ms": sim_time_ms}


def apply_payload(state: dict, payload: dict) -> None:
    new_objects = payload.get("new_objects") or ([payload["new_object"]] if payload.get("new_object") else [])
    if new_objects:
        for item_id in payload["consumed_ids"]:
            state["objects"][item_id]["holder_id"] = f"in:{new_objects[0]['id']}"
        for obj in new_objects:
            state["objects"][obj["id"]] = obj
    for item_id in payload.get("taken_ids", []):
        state["objects"][item_id]["holder_id"] = "player"
    transformed = payload.get("transformed")
    if transformed:
        target = state["objects"][transformed["id"]]
        target.update(condition=transformed["result_state"], holder_id=f"into:{transformed['into'][0]}",
                      became=transformed["into"])
    state["journal"].append(payload["journal_entry"])
    state["last_action"] = payload["journal_entry"]
    state["sim_time_ms"] = payload["sim_time_ms"]
    if "npcs" in payload:
        state["npcs"] = payload["npcs"]
    for update in payload.get("npc_updates", []):
        npc = next(n for n in state["npcs"] if n["id"] == update["id"])
        npc.update(alive=update["alive"], health=update["health"])
        if update["injury"]:
            npc.setdefault("injuries", []).append(update["injury"])
        if not update["alive"] and npc.get("controller"):
            npc["controller"].update(activity="dead", path=[], source="dead")
