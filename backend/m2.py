"""The world's starting things (materials, people's stock and gear, the gate's bar, trees) and the carrying rules.
What they are is content (the level's things, data/content/levels, and its map's trees); picking up and putting
down is decided in code (crafting.quick), everything else by the judge (Try Something)."""

from __future__ import annotations

import copy

import content
import gear
import tuning
from shapes import State

GATE_FIXTURE = "gate_brackets"  # Whatever rests in these holds the gate shut (D-42).


def gate_barred(state: State) -> bool:
    """The gate is shut while anything rests in its brackets."""
    return any(o.get("installed_in") == GATE_FIXTURE for o in state["objects"].values())


def seed_objects(state: State) -> dict[str, dict]:
    """Every thing in the level at the start: its authored things (anything carried with no cell of its own is
    where its holder stands), then every tree on its map as a fellable object. What each portable thing is good
    for in a fight or for the body is read once, here, as code reads it (D-49)."""
    people = {npc["id"]: npc for npc in state.get("npcs", [])}
    objects = {}
    for spec in content.level(state)["things"]:
        holder = people.get(spec.get("carried_by") or spec.get("worn_by") or "") if "x" not in spec else None
        objects[spec["id"]] = authored({**spec, **({"x": holder["x"], "y": holder["y"]} if holder else {})})
    objects.update(_trees(content.map_of(state)))
    for obj in objects.values():
        if "gear" not in obj and "carry" in obj["capabilities"] and obj.get("materials"):
            obj["gear"] = gear.classify(obj)
    return objects


def object_record(
    oid: str,
    name: str,
    x: int,
    y: int,
    mass: float,
    materials: list[str],
    description: str,
    flags: list[str],
    length_m: float | None = None,
    capacity_l: float = 0.0,
    feature: str | None = None,
) -> dict:
    portable = feature is None and mass <= tuning.LIFT_LIMIT_KG
    caps = (
        ["carry"] + (["tie"] if "tieable" in flags else []) + (["fill"] if "container" in flags else [])
        if portable
        else []
    )
    record = {
        "id": oid,
        "name": name,
        "x": x,
        "y": y,
        "mass_kg": mass,
        "owner_id": None,
        "holder_id": None,
        "capabilities": caps,
        "bound_to": [],
        "water_l": 0.0,
        "capacity_l": capacity_l,
        "condition": "usable",
        "materials": materials,
        "description": description,
        "flags": flags,
        "length_m": length_m,
    }
    if feature:
        record["feature"] = feature
    return record


def authored(spec: dict) -> dict:
    """One authored thing as the world holds it: where it lies or who has it, and what it can do."""
    record = object_record(
        spec["id"],
        spec["name"],
        spec["x"],
        spec["y"],
        spec["mass_kg"],
        spec["materials"],
        spec["description"],
        spec["flags"],
        spec.get("length_m"),
        spec.get("capacity_l", 0.0),
        spec.get("feature"),
    )
    record["owner_id"] = spec.get("owner_id")
    if spec.get("capabilities"):
        record["capabilities"] = list(spec["capabilities"])
    for extra in (
        "burning",
        "no_sprite",
        "gear",
        "no_overlay",
        "count",
        "readable",
        "geometry_name",
        "scene_node",
        "area",
        "mixture",
        "hidden",
        "damage",
        "attributes",
    ):  # Fires, building art, gear, books, an obstacle it stands for and its art (brambles in a gap, D-59).
        if spec.get(extra):
            record[extra] = copy.deepcopy(spec[extra])  # The world's own copy, never the content's.
    if spec.get("worn_by") or spec.get("carried_by"):  # Someone's own gear (D-49): on them.
        record["holder_id"] = spec.get("worn_by") or spec.get("carried_by")
        record["capabilities"] = ["carry"] + [c for c in record["capabilities"] if c != "carry"]
        if spec.get("worn_by"):
            record["worn_slots"] = spec["slots"]
    if spec.get("installed_in"):  # e.g. the bar across the gate
        record.update(installed_in=spec["installed_in"], condition="installed")
    if spec.get("water_l"):
        record.update(water_l=spec["water_l"], capabilities=["water_source"])
    return record


def _trees(plan: dict) -> dict[str, dict]:
    """Every tree on the map (an obstacle with a tree kind) as a fellable object."""
    objects = {}
    for obstacle in plan["obstacles"]:
        if not obstacle.get("tree"):
            continue
        kind = plan["trees"][obstacle["tree"]]  # Matches the map's foliage art.
        tree_id = obstacle.get("id") or obstacle["name"].lower()
        tree = object_record(
            tree_id,
            kind["name"],
            obstacle["cells"][0],
            obstacle["cells"][1],
            kind["mass_kg"],
            ["wood"],
            kind["description"],
            ["rigid", "combustible"],
            kind["length_m"],
            feature="tree",
        )
        # The tree's picture and collision already exist in the scene and geometry.
        tree.update(geometry_name=obstacle["name"], scene_node=f"Foliage/{obstacle['name']}")
        objects[tree_id] = tree
    return objects


def seed_m2(state: State) -> dict:
    return {
        "objects": seed_objects(state),
        "agreements": {},
        "journal": [],
        "water_spilled_l": 0.0,
        "last_action": None,
    }


def inventory_mass(state: State) -> float:
    """What the stranger carries, not counting what they wear (D-49: worn armour is on the body, not in the pack)."""
    kit = state["player"].get("equipped") or {}
    worn = {oid for slot, oid in kit.items() if slot in ("head", "body", "arms", "legs", "hands", "feet")}
    return sum(
        o["mass_kg"] + o["water_l"]
        for o in state["objects"].values()
        if o["holder_id"] == "player" and o["id"] not in worn
    )
