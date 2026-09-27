"""Milestone 2 deterministic physical-action slice.

The parser is deliberately bounded: it never invents an entity, permission, tool,
or physical effect from prose. A later milestone can add a judged invention path.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

REACH_CELLS = 2.5
CARRY_LIMIT_KG = 20.0
_ROOT = Path(__file__).resolve().parents[1]
WORLD_CONTENT = json.loads((_ROOT / "data" / "content" / "world_objects.json").read_text(encoding="utf-8"))
_GEOMETRY = json.loads((_ROOT / "data" / "world_geometry.json").read_text(encoding="utf-8"))


def seed_objects(seed_version: int = 3) -> dict[str, dict]:
    specs = [
        ("branch_a", "fallen branch", 47, 67, 1.2, None, ["carry", "tie"]),
        ("branch_b", "fallen branch", 50, 67, 1.2, None, ["carry", "tie"]),
        ("cord_a", "short cord", 49, 66, 0.2, None, ["carry", "tie"]),
        ("stone_a", "loose stone", 47, 65, 2.0, None, ["carry", "support"]),
        ("bucket_hessa", "wooden bucket", 35, 52, 0.5, "npc_hessa_marr", ["carry", "fill", "pour"]),
        ("trough_hessa", "water trough", 36, 52, 80.0, "npc_hessa_marr", ["water_source"]),
        ("wood_tomas", "wood plank", 64, 28, 4.0, "npc_tomas_reed", ["carry", "tie", "support"]),
    ]
    if seed_version >= 4:
        specs += [(oid, name, x, y, mass, None, ["carry"] + (["tie"] if "tieable" in MATERIAL_SEED[oid][2] else []))
                  for oid, (name, x, y, mass) in NEW_PUBLIC_MATERIALS.items()]
    objects = {oid: {"id": oid, "name": name, "x": x, "y": y, "mass_kg": mass,
                     "owner_id": owner, "holder_id": None, "capabilities": caps,
                     "bound_to": [], "water_l": 80.0 if oid == "trough_hessa" else 0.0,
                     "capacity_l": 1.0 if oid == "bucket_hessa" else 0.0,
                     "condition": "usable"} for oid, name, x, y, mass, owner, caps in specs}
    if seed_version >= 4:
        # Crafting needs to know what things are made of; earlier seeds replay unchanged.
        for oid, obj in objects.items():
            materials, description, flags, length_m = MATERIAL_SEED[oid]
            obj.update(materials=materials, description=description, flags=flags, length_m=length_m)
    if seed_version >= 5:
        objects.update(_seed5_objects(seed_version))
    return objects


def _object_record(oid: str, name: str, x: int, y: int, mass: float, materials: list[str], description: str,
                   flags: list[str], length_m: float | None = None, capacity_l: float = 0.0,
                   feature: str | None = None) -> dict:
    portable = feature is None and mass <= CARRY_LIMIT_KG
    caps = (["carry"] + (["tie"] if "tieable" in flags else []) + (["fill"] if "container" in flags else [])
            if portable else [])
    record = {"id": oid, "name": name, "x": x, "y": y, "mass_kg": mass, "owner_id": None, "holder_id": None,
              "capabilities": caps, "bound_to": [], "water_l": 0.0, "capacity_l": capacity_l,
              "condition": "usable", "materials": materials, "description": description, "flags": flags,
              "length_m": length_m}
    if feature:
        record["feature"] = feature
    return record


def _seed5_objects(seed_version: int = 5) -> dict[str, dict]:
    """Materials, people's stock and saplings from data/content, plus every map tree as a fellable object."""
    objects = {}
    for spec in WORLD_CONTENT["objects"]:
        if spec.get("since_seed", 5) > seed_version:
            continue  # Older journeys replay the world they began with.
        record = _object_record(
            spec["id"], spec["name"], spec["x"], spec["y"], spec["mass_kg"], spec["materials"],
            spec["description"], spec["flags"], spec.get("length_m"), spec.get("capacity_l", 0.0),
            spec.get("feature"))
        record["owner_id"] = spec.get("owner_id")
        if spec.get("water_l"):
            record.update(water_l=spec["water_l"], capabilities=["water_source"])
        objects[spec["id"]] = record
    kinds = WORLD_CONTENT["trees"]
    for obstacle in _GEOMETRY["obstacles"]:
        if not obstacle["name"].startswith("Tree"):
            continue
        number = int(obstacle["name"][4:])
        kind = kinds["cypress" if number % 3 == 0 else "oak"]  # Matches the Foliage art in main.tscn.
        tree_id = f"tree_{number:02d}"
        tree = _object_record(tree_id, kind["name"], obstacle["cells"][0], obstacle["cells"][1], kind["mass_kg"],
                              ["wood"], kind["description"], ["rigid", "combustible"], kind["length_m"],
                              feature="tree")
        # The tree's picture and collision already exist in the scene and geometry.
        tree.update(geometry_name=obstacle["name"], scene_node=f"Foliage/{obstacle['name']}")
        objects[tree_id] = tree
    return objects


# Loose public materials along the south road, added for the crafting slice (seed 4).
NEW_PUBLIC_MATERIALS = {
    "flint_a": ("flint shard", 45, 66, 0.3),
    "stone_b": ("flat stone", 51, 65, 1.5),
    "grass_a": ("bundle of dry grass", 44, 64, 0.2),
    "reeds_a": ("hollow reeds", 53, 66, 0.3),
    "vine_a": ("length of vine", 43, 67, 0.4),
    "bark_a": ("strip of bark", 52, 63, 0.2),
    "resin_a": ("lump of pine resin", 46, 63, 0.1),
}

# id: (materials, description, flags, length_m)
MATERIAL_SEED = {
    "branch_a": (["wood"], "A dry, fairly straight fallen branch about 1.5 m long and wrist-thick.",
                 ["rigid", "combustible", "floats"], 1.5),
    "branch_b": (["wood"], "A dry fallen branch about 1.5 m long, slightly crooked at one end.",
                 ["rigid", "combustible", "floats"], 1.5),
    "cord_a": (["plant fiber"], "A short length of twisted plant-fibre cord, about 1 m long.",
               ["flexible", "tieable", "combustible"], 1.0),
    "stone_a": (["stone"], "A loose, rounded stone the size of a fist, heavy for its size.", ["rigid"], None),
    "bucket_hessa": (["wood", "iron"], "Hessa's wooden bucket with an iron band and rope handle.",
                     ["container", "watertight"], None),
    "trough_hessa": (["wood"], "A long wooden water trough in Hessa's yard.", ["container", "watertight"], None),
    "wood_tomas": (["wood"], "A sawn plank, 2 m long, 20 cm wide and 4 cm thick.",
                   ["rigid", "combustible", "floats", "stable_support"], 2.0),
    "flint_a": (["flint"], "A palm-sized shard of grey flint with a thin, glassy, very sharp edge.",
                ["rigid", "sharp_edge"], None),
    "stone_b": (["stone"], "A flat, heavy stone about as wide as two hands.", ["rigid", "stable_support"], None),
    "grass_a": (["dry grass"], "An armful-sized bundle of dry, brittle grass.", ["flexible", "combustible"], None),
    "reeds_a": (["reed"], "A handful of hollow reed stems, each about 1.2 m long.",
                ["rigid", "floats", "combustible"], 1.2),
    "vine_a": (["vine"], "A tough, fresh length of climbing vine about 2 m long.", ["flexible", "tieable"], 2.0),
    "bark_a": (["bark"], "A long strip of pliable bark peeled from a fallen trunk.",
               ["flexible", "floats", "combustible"], 0.6),
    "resin_a": (["pine resin"], "A sticky amber lump of pine resin the size of a walnut.",
                ["adhesive", "combustible"], None),
}


def seed_m2(seed_version: int = 3) -> dict:
    return {"objects": seed_objects(seed_version), "agreements": {}, "journal": [],
            "water_spilled_l": 0.0, "last_action": None}


def nearby(state: dict) -> list[dict]:
    return [copy.deepcopy(o) for o in state["objects"].values() if accessible(state, o)]


def accessible(state: dict, obj: dict) -> bool:
    if obj["holder_id"] == "player":
        return True
    if obj["holder_id"] is not None:
        return False
    return math.dist((state["player"]["x"], state["player"]["y"]), (obj["x"], obj["y"])) <= REACH_CELLS


def npc_near(state: dict, npc_id: str) -> bool:
    return any(n["id"] == npc_id and math.dist((state["player"]["x"], state["player"]["y"]),
               (n["x"], n["y"])) <= REACH_CELLS for n in state["npcs"])


def inventory_mass(state: dict) -> float:
    return sum(o["mass_kg"] + o["water_l"] for o in state["objects"].values()
               if o["holder_id"] == "player")


def is_bound(state: dict, object_id: str) -> bool:
    obj = state["objects"][object_id]
    return bool(obj["bound_to"]) or any(object_id in other["bound_to"]
                                         for other in state["objects"].values())


def parse(text: str, selected: list[str], state: dict) -> tuple[list[dict], str | None]:
    """Return ordered, explicitly bound PlanSteps or a reason to clarify."""
    clauses = re.split(r"\s+(?:and then|then)\s+", text.strip().lower())
    if not 1 <= len(clauses) <= 3 or any(not c.strip() for c in clauses):
        return [], "Use one to three clear steps separated by 'then'."
    selected_entities = {i: state["objects"].get(i) or next((n for n in state["npcs"] if n["id"] == i), None)
                         for i in selected}
    if any(v is None for v in selected_entities.values()):
        return [], "One selected target no longer exists. Reopen Try Something."
    plan = []
    for index, clause in enumerate(clauses):
        match = re.match(r"^(inspect|examine|look at|take|pick up|drop|put down|give|tie|untie|fill|pour|ask|request)\b", clause)
        if not match:
            return [], f"Unsupported step: '{clause}'. Try inspect, take, drop, give, tie, untie, fill, pour, or ask Hessa for work."
        verb = match.group(1)
        operation = {"examine": "inspect", "look at": "inspect", "pick up": "take", "put down": "drop",
                     "request": "ask"}.get(verb, verb)
        explicit = [i for i in selected if i.replace("_", " ") in clause or
                    re.search(r"\b" + re.escape(i.split("_")[-2] + " " + i.split("_")[-1]) + r"\b", clause)]
        mentions = (explicit + [i for i, entity in selected_entities.items()
                                if i.startswith("npc_") and entity["name"].lower() in clause and i not in explicit]) if explicit else [
            i for i, entity in selected_entities.items() if entity["name"].lower() in clause or
            entity["name"].lower().split()[-1] in clause]
        if not mentions and len(selected) == 1:
            mentions = list(selected)
        if operation == "ask":
            if "work" not in clause or "npc_hessa_marr" not in mentions:
                return [], "For this slice, select Hessa and ask her for work."
            mentions = ["npc_hessa_marr"]
        elif operation == "give":
            if len(mentions) != 2 or "npc_hessa_marr" not in mentions:
                return [], "Select one object and Hessa, then name both in the give action."
        elif operation == "tie":
            if len(mentions) < 2:
                # 'tie branches with cord' mentions both identically named branches.
                mentions = [i for i, e in selected_entities.items() if e and
                            (e["name"].split()[-1] in clause or e["name"] in clause)]
            if len(mentions) < 2:
                return [], "Select and name both the cord and what you want to tie."
        elif operation == "untie":
            if len(mentions) != 1 or not mentions[0].startswith("cord_"):
                return [], "Select and name one tied cord to untie."
        elif len(mentions) != 1:
            return [], "Select and name one clear target for each step."
        required = {"take": ["carry"], "tie": ["tie"], "fill": ["fill"], "pour": ["pour"]}.get(operation, [])
        plan.append({"step_id": f"step_{index + 1}", "operation_key": operation,
                     "actor_id": "player", "input_refs": [{"existing_entity_id": i} for i in mentions],
                     "output_bindings": [], "depends_on": [f"step_{index}"] if index else [],
                     "required_capabilities": required, "required_skill": None,
                     "effort_seconds": {"inspect": 0, "take": 2, "drop": 2, "give": 2, "tie": 2,
                                        "untie": 2, "fill": 2, "pour": 2, "ask": 5}[operation],
                     "risk_tags": [], "status": "pending"})
    return plan, None


def _fail(category: str, reason: str) -> tuple[str, str]:
    return category, reason


def _complete_hessa_if_ready(state: dict) -> bool:
    agreement = state["agreements"].get("hessa_debris")
    if not agreement or agreement["status"] != "accepted":
        return False
    if not all(b["holder_id"] == "npc_hessa_marr" or
               (b["holder_id"] is None and math.dist((b["x"], b["y"]), (34, 51)) <= 3)
               for b in (state["objects"]["branch_a"], state["objects"]["branch_b"])):
        return False
    agreement["status"] = "fulfilled"
    agreement["evidence_event_ids"] = [e["event_id"] for e in state["journal"]
        if e["category"] == "success" and e["step"]["operation_key"] in ("drop", "give")
        and any(r["existing_entity_id"] in ("branch_a", "branch_b") for r in e["step"]["input_refs"])
        and (e["step"]["operation_key"] == "give" or
             math.dist(e.get("player_cell", (999, 999)), (34, 51)) <= 3)]
    agreement["evidence_event_ids"].append(state["event_seq"] + 1)
    return True


def apply_step(state: dict, step: dict) -> tuple[str, str]:
    """Mutate only a disposable state copy. Caller commits one step atomically."""
    op = step["operation_key"]
    ids = [r["existing_entity_id"] for r in step["input_refs"]]
    if op == "ask":
        if not npc_near(state, "npc_hessa_marr"):
            return _fail("blocked", "Hessa is too far away to hear you.")
        if "hessa_debris" in state["agreements"]:
            return _fail("blocked", "Hessa has already answered this work request. Check the agreement in your journal.")
        state["agreements"]["hessa_debris"] = {
            "id": "hessa_debris", "type": "task_for_reward", "proposer_id": "npc_hessa_marr",
            "acceptor_ids": ["player"], "authorized_issuer_id": "npc_hessa_marr",
            "obligations": ["Bring both fallen branches to Hessa's yard and drop them nearby."],
            "completion_predicate": "both_branch_ids_at_hessa_yard", "reward_effects": ["permission_use_bucket"],
            "resource_limits": {"bucket_id": "bucket_hessa"}, "deadline_tick": None,
            "supervision_scope": "inn_yard", "evidence_event_ids": [], "status": "accepted"}
        return "success", "Hessa agrees: clear the two fallen branches from the road. Bring and drop both near her yard; then you may use her bucket."
    if op == "give":
        source_ids = [i for i in ids if i != "npc_hessa_marr"]
        if len(source_ids) != 1 or source_ids[0] not in state["objects"]:
            return _fail("needs_clarification", "Choose one object to give to Hessa.")
        obj = state["objects"][source_ids[0]]
        if not npc_near(state, "npc_hessa_marr"):
            return _fail("blocked", "Hessa is too far away to receive it.")
        if obj["holder_id"] != "player":
            return _fail("blocked", "You must be carrying the object you offer.")
        if (obj["id"] not in ("branch_a", "branch_b") or
                state["agreements"].get("hessa_debris", {}).get("status") != "accepted"):
            return _fail("blocked", "Hessa has not agreed to receive that object.")
        if is_bound(state, obj["id"]):
            return _fail("blocked", "Untie the object before handing it over.")
        obj["holder_id"] = "npc_hessa_marr"  # Possession changes; provenance/ownership does not.
        obj["x"], obj["y"] = 34, 51
        if _complete_hessa_if_ready(state):
            return "success", "Hessa receives the second branch. The task is fulfilled; you may use her bucket."
        return "success", "Hessa receives the branch for the agreed task."
    for oid in ids:
        if oid not in state["objects"]:
            if op == "inspect":
                npc = next((n for n in state["npcs"] if n["id"] == oid), None)
                if npc and npc_near(state, oid):
                    return "success", f"{npc['name']}: {npc['role']}. You can see where they stand, but not their private thoughts."
            return _fail("blocked", f"{oid} no longer exists.")
        if not accessible(state, state["objects"][oid]):
            return _fail("blocked", f"{state['objects'][oid]['name']} is out of reach or held by someone else.")
        if state["objects"][oid]["condition"] != "usable":
            return _fail("blocked", f"{state['objects'][oid]['name']} is unusable.")
    obj = state["objects"][ids[0]]
    if op == "inspect":
        owner = obj["owner_id"] or "no known owner"
        detail = f"{obj['name']}: {obj['mass_kg']} kg; {obj['condition']}; owner: {owner}; capabilities: {', '.join(obj['capabilities'])}."
        if obj["capacity_l"]:
            detail += f" Holds {obj['water_l']}/{obj['capacity_l']} L of water."
        if obj["bound_to"]:
            detail += f" Tied to {', '.join(obj['bound_to'])}."
        return "success", detail
    if op == "take":
        if "carry" not in obj["capabilities"]:
            return _fail("blocked", "That object is fixed in place or too heavy to carry.")
        if obj["holder_id"] == "player":
            return _fail("blocked", "You already carry it.")
        if obj["owner_id"] not in (None, "player") and not (obj["id"] == "bucket_hessa" and
                                   state["agreements"].get("hessa_debris", {}).get("status") == "fulfilled"):
            return _fail("blocked", f"{obj['name']} belongs to someone else. You have no permission to take it.")
        if inventory_mass(state) + obj["mass_kg"] + obj["water_l"] > CARRY_LIMIT_KG:
            return _fail("blocked", "That would exceed your 20 kg carrying limit.")
        if is_bound(state, obj["id"]):
            return _fail("blocked", "Untie it before moving it.")
        obj["holder_id"] = "player"
        return "success", f"You pick up the {obj['name']}."
    if op == "drop":
        if obj["holder_id"] != "player":
            return _fail("blocked", "You are not carrying it.")
        if is_bound(state, obj["id"]):
            return _fail("blocked", "Untie it before dropping it.")
        obj["holder_id"] = None
        obj["x"], obj["y"] = state["player"]["x"], state["player"]["y"]
        if obj["id"] in ("branch_a", "branch_b") and _complete_hessa_if_ready(state):
            return "success", "Both branches are in Hessa's yard. The task is fulfilled; Hessa now permits you to use her bucket."
        return "success", f"You put down the {obj['name']}."
    if op == "tie":
        cords = [state["objects"][i] for i in ids if i.startswith("cord_")]
        targets = [state["objects"][i] for i in ids if not i.startswith("cord_")]
        if len(cords) != 1 or not targets:
            return _fail("needs_clarification", "Choose one cord and at least one other object.")
        if any(o["holder_id"] != "player" for o in cords + targets):
            return _fail("blocked", "Carry the cord and each object before tying them.")
        if cords[0]["bound_to"]:
            return _fail("blocked", "That cord is already tied. Untie it first.")
        cords[0]["bound_to"] = [o["id"] for o in targets]
        return "success", "You tie the cord around " + ", ".join(o["name"] for o in targets) + "."
    if op == "untie":
        cord = next((state["objects"][i] for i in ids if i.startswith("cord_")), None)
        if cord is None or not cord["bound_to"]:
            return _fail("blocked", "Select a cord that is tied to something.")
        if cord["holder_id"] != "player":
            return _fail("blocked", "You must hold the cord to untie it.")
        cord["bound_to"] = []
        return "success", "You untie the cord."
    if op == "fill":
        if obj["id"] != "bucket_hessa":
            return _fail("blocked", "Only a water container can be filled.")
        source = state["objects"]["trough_hessa"]
        if obj["holder_id"] != "player" or not accessible(state, source):
            return _fail("blocked", "Carry the bucket to the water trough first.")
        if obj["water_l"] >= obj["capacity_l"]:
            return _fail("blocked", "The bucket is already full.")
        if source["water_l"] < 1.0:
            return _fail("blocked", "The trough is empty.")
        obj["water_l"] = obj["capacity_l"]
        source["water_l"] -= 1.0
        return "success", "You fill the bucket with 1 L of water from the trough."
    if op == "pour":
        if obj["id"] != "bucket_hessa" or obj["holder_id"] != "player" or obj["water_l"] <= 0:
            return _fail("blocked", "Carry a bucket containing water before pouring.")
        state["water_spilled_l"] += obj["water_l"]
        obj["water_l"] = 0.0
        return "success", "You pour 1 L of water onto the ground."
    return _fail("unsupported", "That operation is not implemented in this slice.")
