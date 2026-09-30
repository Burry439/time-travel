"""The world's seeded objects (materials, people's stock, trees) and the carrying rules.

The old Milestone 2 phrase parser is retired: Try Something goes to the judge, and picking up or
putting down is decided in code (crafting.quick).
"""

from __future__ import annotations

import content
import gear
import tuning

GATE_FIXTURE = "gate_brackets"  # Whatever rests in these holds the gate shut (seed 9, D-42).
GATE_BAR_SEED = 9
GATEWAY = (48, 8)  # The middle of the gate opening.


def gate_barred(state: dict) -> bool:
    """Seed 9 on: the gate is shut while anything rests in its brackets. Older journeys: always barred."""
    if state.get("seed_version", 0) < GATE_BAR_SEED:
        return True
    return any(o.get("installed_in") == GATE_FIXTURE for o in state["objects"].values())


WORLD_CONTENT = content.WORLD_OBJECTS


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
        specs += [
            (oid, name, x, y, mass, None, ["carry"] + (["tie"] if "tieable" in MATERIAL_SEED[oid][2] else []))
            for oid, (name, x, y, mass) in NEW_PUBLIC_MATERIALS.items()
        ]
    objects = {
        oid: {
            "id": oid,
            "name": name,
            "x": x,
            "y": y,
            "mass_kg": mass,
            "owner_id": owner,
            "holder_id": None,
            "capabilities": caps,
            "bound_to": [],
            "water_l": 80.0 if oid == "trough_hessa" else 0.0,
            "capacity_l": 1.0 if oid == "bucket_hessa" else 0.0,
            "condition": "usable",
        }
        for oid, name, x, y, mass, owner, caps in specs
    }
    if seed_version >= 4:
        # Crafting needs to know what things are made of; earlier seeds replay unchanged.
        for oid, obj in objects.items():
            materials, description, flags, length_m = MATERIAL_SEED[oid]
            obj.update(materials=materials, description=description, flags=flags, length_m=length_m)
    if seed_version >= 5:
        objects.update(_seed5_objects(seed_version))
    if seed_version >= 10:
        # What each portable thing is good for in a fight or for the body, as code reads it (D-49).
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
    portable = feature is None and mass <= tuning.CARRY_LIMIT_KG
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


def _seed5_objects(seed_version: int = 5) -> dict[str, dict]:
    """Materials, people's stock and saplings from data/content, plus every map tree as a fellable object."""
    objects = {}
    for spec in WORLD_CONTENT["objects"]:
        if spec.get("since_seed", 5) > seed_version:
            continue  # Older journeys replay the world they began with.
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
        for extra in (
            "burning",
            "no_sprite",
            "gear",
            "no_overlay",
            "count",
            "readable",
        ):  # Fires, building art, gear, books.
            if spec.get(extra):
                record[extra] = spec[extra]
        if spec.get("worn_by") or spec.get("carried_by"):  # Someone's own gear (seed 10, D-49): on them.
            record["holder_id"] = spec.get("worn_by") or spec.get("carried_by")
            record["capabilities"] = ["carry"] + [c for c in record["capabilities"] if c != "carry"]
            if spec.get("worn_by"):
                record["worn_slots"] = spec["slots"]
        if spec.get("installed_in"):  # e.g. the bar across the gate (seed 9)
            record.update(installed_in=spec["installed_in"], condition="installed")
        if spec.get("water_l"):
            record.update(water_l=spec["water_l"], capabilities=["water_source"])
        objects[spec["id"]] = record
    kinds = WORLD_CONTENT["trees"]
    for obstacle in content.GEOMETRY["obstacles"]:
        if not obstacle["name"].startswith("Tree"):
            continue
        number = int(obstacle["name"][4:])
        kind = kinds["cypress" if number % 3 == 0 else "oak"]  # Matches the Foliage art in main.tscn.
        tree_id = f"tree_{number:02d}"
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
    "branch_a": (
        ["wood"],
        "A dry, fairly straight fallen branch about 1.5 m long and wrist-thick.",
        ["rigid", "combustible", "floats"],
        1.5,
    ),
    "branch_b": (
        ["wood"],
        "A dry fallen branch about 1.5 m long, slightly crooked at one end.",
        ["rigid", "combustible", "floats"],
        1.5,
    ),
    "cord_a": (
        ["plant fiber"],
        "A short length of twisted plant-fibre cord, about 1 m long.",
        ["flexible", "tieable", "combustible"],
        1.0,
    ),
    "stone_a": (["stone"], "A loose, rounded stone the size of a fist, heavy for its size.", ["rigid"], None),
    "bucket_hessa": (
        ["wood", "iron"],
        "Hessa's wooden bucket with an iron band and rope handle.",
        ["container", "watertight"],
        None,
    ),
    "trough_hessa": (["wood"], "A long wooden water trough in Hessa's yard.", ["container", "watertight"], None),
    "wood_tomas": (
        ["wood"],
        "A sawn plank, 2 m long, 20 cm wide and 4 cm thick.",
        ["rigid", "combustible", "floats", "stable_support"],
        2.0,
    ),
    "flint_a": (
        ["flint"],
        "A palm-sized shard of grey flint with a thin, glassy, very sharp edge.",
        ["rigid", "sharp_edge"],
        None,
    ),
    "stone_b": (["stone"], "A flat, heavy stone about as wide as two hands.", ["rigid", "stable_support"], None),
    "grass_a": (["dry grass"], "An armful-sized bundle of dry, brittle grass.", ["flexible", "combustible"], None),
    "reeds_a": (
        ["reed"],
        "A handful of hollow reed stems, each about 1.2 m long.",
        ["rigid", "floats", "combustible"],
        1.2,
    ),
    "vine_a": (["vine"], "A tough, fresh length of climbing vine about 2 m long.", ["flexible", "tieable"], 2.0),
    "bark_a": (
        ["bark"],
        "A long strip of pliable bark peeled from a fallen trunk.",
        ["flexible", "floats", "combustible"],
        0.6,
    ),
    "resin_a": (
        ["pine resin"],
        "A sticky amber lump of pine resin the size of a walnut.",
        ["adhesive", "combustible"],
        None,
    ),
}


def seed_m2(seed_version: int = 3) -> dict:
    return {
        "objects": seed_objects(seed_version),
        "agreements": {},
        "journal": [],
        "water_spilled_l": 0.0,
        "last_action": None,
    }


def inventory_mass(state: dict) -> float:
    """What the stranger carries, not counting what they wear (D-49: worn armour is on the body, not in the pack)."""
    kit = state["player"].get("equipped") or {}
    worn = {oid for slot, oid in kit.items() if slot in ("head", "body", "arms", "legs", "hands", "feet")}
    return sum(
        o["mass_kg"] + o["water_l"]
        for o in state["objects"].values()
        if o["holder_id"] == "player" and o["id"] not in worn
    )
