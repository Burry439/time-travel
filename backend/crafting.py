"""Crafting slice: what the judge sees, what code allows, and the committed effects.

Models propose; this module decides what a proposal may change (GDD section 6.2).
Each validator decision is recorded as a note so the developer trace shows why.
"""
from __future__ import annotations

import json
from pathlib import Path

import m2

ROOT = Path(__file__).resolve().parents[1]
CONTENT = json.loads((ROOT / "data" / "content" / "materials.json").read_text(encoding="utf-8"))
MAX_EFFORT_SECONDS = 600
PRIOR_RULINGS = 10
# Flags describing an active state need an input that can cause it. Without one the
# flag becomes an untested capability instead of a physical fact.
ACTIVE_FLAGS = {
    "magnetized": ({"magnet_source", "magnetized"}, "might become magnetic if touched to a real magnet"),
    "magnet_source": ({"magnet_source", "magnetized"}, "might attract iron if it were magnetic"),
    "light_source": ({"light_source", "heat_source"}, "could give light if lit"),
    "heat_source": ({"heat_source"}, "could give heat if lit"),
}
OPERATION_CAPABILITIES = {"tieable": "tie", "container": "fill"}


def available_items(state: dict) -> list[dict]:
    """Carried items plus loose, unowned items within reach."""
    items = []
    for obj in state["objects"].values():
        carried = obj["holder_id"] == "player"
        loose = obj["holder_id"] is None and obj["owner_id"] is None and m2.accessible(state, obj)
        if (carried or loose) and "water_source" not in obj["capabilities"] and obj["condition"] == "usable":
            items.append(obj)
    return items


def _judge_view(obj: dict) -> dict:
    return {"id": obj["id"], "name": obj["name"], "description": obj.get("description", ""),
            "materials": obj.get("materials", []), "mass_kg": obj["mass_kg"],
            "length_m": obj.get("length_m"), "flags": obj.get("flags", []),
            "carried_by_player": obj["holder_id"] == "player",
            "consumable": obj["owner_id"] in (None, "player")}


def prior_rulings(state: dict) -> list[dict]:
    rulings = [{"intention": e["text"], "outcome": e["category"], "reason": e["reason"],
                "made": e.get("made_name"), "precedent_key": e.get("precedent_key")}
               for e in state["journal"] if e.get("kind") == "craft" and e["category"] != "unresolved"]
    return rulings[-PRIOR_RULINGS:]


def build_context(state: dict, text: str, selected_ids: list[str]) -> dict:
    items = available_items(state)
    ids = {o["id"] for o in items}
    return {"player_intention": text,
            "highlighted_item_ids": [i for i in selected_ids if i in ids],
            "player_cell": [state["player"]["x"], state["player"]["y"]],
            "available_items": [_judge_view(o) for o in items],
            "prior_rulings": prior_rulings(state)}


def _verdict(category: str, reason: str, notes: list[str], effort: int = 0, **extra) -> dict:
    return {"category": category, "reason": reason, "effort_seconds": effort, "notes": notes,
            "consumed_ids": [], "tool_ids": [], "new_spec": None, "precedent_key": None, **extra}


def _dedupe(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _material_matches(material: str, inputs: set[str]) -> str | None:
    """Loose match so 'grass' fits 'dry grass'; returns the canonical input material."""
    if material in inputs:
        return material
    return next((m for m in sorted(inputs) if material in m or m in material), None)


def validate(state: dict, judged: dict | None, service_error: str | None = None) -> dict:
    """Turn a judge proposal into what code will actually commit, against the current state."""
    notes: list[str] = []
    if judged is None:
        return _verdict("unresolved", service_error or "The judge could not be reached. Nothing changed.", notes)
    outcome, reason = judged["outcome"], judged["reason"].strip() or "Nothing happens."
    effort = max(0, min(MAX_EFFORT_SECONDS, int(judged["effort_seconds"])))
    key = judged.get("precedent_key")
    if outcome != "success" and judged.get("new_object"):
        notes.append(f"Ignored new_object because outcome is '{outcome}'.")
    if outcome == "needs_clarification":
        return _verdict(outcome, judged.get("clarifying_question") or reason, notes, precedent_key=key)
    if outcome in ("blocked", "unsupported"):
        if effort:
            notes.append(f"Effort {effort}s ignored: '{outcome}' spends no time.")
        return _verdict(outcome, reason, notes, precedent_key=key)
    if outcome == "failed":
        return _verdict("failed", reason, notes, max(1, effort), precedent_key=key)

    spec = judged.get("new_object")
    if not spec:
        return _verdict("unresolved", "The attempt could not be resolved. Nothing changed.",
                        notes + ["Rejected: outcome 'success' without a new_object."])
    available = {o["id"]: o for o in available_items(state)}
    consumes = _dedupe(spec["consumes"])
    tools = [i for i in _dedupe(spec["tools_used"]) if i not in consumes]

    def reject(note: str) -> dict:
        return _verdict("unresolved", "The attempt could not be resolved. Nothing changed.", notes + [f"Rejected: {note}"])

    missing = [i for i in consumes + tools if i not in available]
    if missing:
        return reject(f"proposal used items that are not available now: {missing}")
    if not consumes:
        return reject("a new object must be made from at least one consumed item")
    not_ours = [i for i in consumes if available[i]["owner_id"] not in (None, "player")]
    if not_ours:
        return reject(f"proposal consumed someone else's property: {not_ours}")
    for item_id in consumes:
        partners = set(state["objects"][item_id]["bound_to"]) | {
            o["id"] for o in state["objects"].values() if item_id in o["bound_to"]}
        if not partners <= set(consumes):
            return reject(f"{item_id} is tied to {sorted(partners - set(consumes))}, which is not part of the new object")

    input_materials = {m.lower() for i in consumes for m in available[i].get("materials", [])}
    materials: list[str] = []
    for material in (m.lower().strip() for m in spec["materials"]):
        match = _material_matches(material, input_materials)
        if match is None:
            notes.append(f"Stripped material '{material}': no consumed item is made of it.")
        elif match not in materials:
            materials.append(match)
    if not materials:
        materials = sorted(input_materials)
        notes.append(f"Materials set from consumed items: {materials}.")

    input_mass = round(sum(available[i]["mass_kg"] for i in consumes), 3)
    mass = float(spec["mass_kg"])
    if not 0 < mass <= input_mass:
        clamped = max(0.01, min(mass, input_mass))
        notes.append(f"Mass {mass} kg clamped to {clamped} kg (consumed items weigh {input_mass} kg).")
        mass = clamped

    support = {f for i in consumes + tools for f in available[i].get("flags", [])}
    flags: list[str] = []
    capabilities = [dict(c) for c in spec["capabilities"]]
    for flag in _dedupe(spec["flags"]):
        causes = ACTIVE_FLAGS.get(flag)
        if causes and not causes[0] & support:
            notes.append(f"Stripped flag '{flag}': no input can cause it. Recorded as untested.")
            capabilities.append({"text": causes[1], "status": "untested"})
        elif flag == "ferromagnetic" and "iron" not in materials:
            notes.append("Stripped flag 'ferromagnetic': the object contains no iron.")
        else:
            flags.append(flag)

    capacity = spec.get("capacity_l")
    if capacity and "container" not in flags:
        notes.append("Dropped capacity_l: the object is not flagged as a container.")
        capacity = None
    if effort < 1:
        notes.append("Effort raised to 1 s: making something takes time.")
    new_spec = {"name": spec["name"].strip().lower()[:60] or "made thing",
                "description": spec["description"].strip()[:400], "materials": materials,
                "mass_kg": round(mass, 3), "length_m": _positive(spec.get("length_m")),
                "capacity_l": _positive(capacity), "rated_load_kg": _positive(spec.get("rated_load_kg")),
                "flags": flags, "known_capabilities": capabilities[:6]}
    return _verdict("success", reason, notes, max(1, effort), consumed_ids=consumes, tool_ids=tools,
                    new_spec=new_spec, precedent_key=key)


def _positive(value) -> float | None:
    return round(float(value), 3) if value is not None and float(value) > 0 else None


def placeholder_category(materials: list[str]) -> str:
    categories = CONTENT["placeholder_categories"]
    return next((categories[m] for m in materials if m in categories), "bundle")


def build_payload(state: dict, run_id: str, text: str, verdict: dict, trace_id: str,
                  sim_time_ms: int) -> dict:
    """Event payload holding only deltas; apply_payload replays it."""
    event_id = state["event_seq"] + 1
    new_object = None
    if verdict["category"] == "success":
        spec = verdict["new_spec"]
        new_id = f"made_{event_id}"
        consumed_carried = sum(state["objects"][i]["mass_kg"] + state["objects"][i]["water_l"]
                               for i in verdict["consumed_ids"] if state["objects"][i]["holder_id"] == "player")
        fits = m2.inventory_mass(state) - consumed_carried + spec["mass_kg"] <= m2.CARRY_LIMIT_KG
        caps = ["carry"] + [op for flag, op in OPERATION_CAPABILITIES.items() if flag in spec["flags"]]
        new_object = {
            "id": new_id, "name": spec["name"], "description": spec["description"],
            "x": state["player"]["x"], "y": state["player"]["y"], "mass_kg": spec["mass_kg"],
            "owner_id": "player", "holder_id": "player" if fits else None, "capabilities": caps,
            "bound_to": [], "water_l": 0.0, "capacity_l": spec["capacity_l"] or 0.0, "condition": "usable",
            "materials": spec["materials"], "flags": spec["flags"], "length_m": spec["length_m"],
            "rated_load_kg": spec["rated_load_kg"], "known_capabilities": spec["known_capabilities"],
            "components": verdict["consumed_ids"], "tools_used": verdict["tool_ids"],
            "created_by": "player", "created_event_id": event_id, "created_text": text,
            "sprite_asset_id": f"spr_{run_id[:8]}_{new_id}",
            "placeholder": placeholder_category(spec["materials"]),
        }
        if not fits:
            verdict["notes"].append("New object is too heavy to carry with the current load; left at the player's feet.")
    refs = verdict["consumed_ids"] + verdict["tool_ids"]
    entry = {"kind": "craft", "text": text, "category": verdict["category"], "reason": verdict["reason"],
             "step": {"step_id": "step_1", "operation_key": "craft", "actor_id": "player",
                      "input_refs": [{"existing_entity_id": i} for i in refs], "output_bindings":
                      [new_object["id"]] if new_object else [], "depends_on": [], "required_capabilities": [],
                      "required_skill": None, "effort_seconds": verdict["effort_seconds"], "risk_tags": [],
                      "status": "completed" if new_object else verdict["category"]},
             "player_cell": [state["player"]["x"], state["player"]["y"]], "event_id": event_id,
             "made": new_object["id"] if new_object else None,
             "made_name": new_object["name"] if new_object else None,
             "precedent_key": verdict["precedent_key"], "trace_id": trace_id}
    return {"consumed_ids": verdict["consumed_ids"] if new_object else [], "new_object": new_object,
            "journal_entry": entry, "sim_time_ms": sim_time_ms}


def apply_payload(state: dict, payload: dict) -> None:
    new_object = payload["new_object"]
    if new_object:
        for item_id in payload["consumed_ids"]:
            state["objects"][item_id]["holder_id"] = f"in:{new_object['id']}"
        state["objects"][new_object["id"]] = new_object
    state["journal"].append(payload["journal_entry"])
    state["last_action"] = payload["journal_entry"]
    state["sim_time_ms"] = payload["sim_time_ms"]
    if "npcs" in payload:
        state["npcs"] = payload["npcs"]
