"""What the judge is shown of the world around the stranger: what they carry and can walk to, who is nearby
and in what state, where water is, and how earlier attempts were ruled (GDD 6.1). Only what's here can be
named in a proposal; crafting.validate checks every proposal against the world as it is."""

from __future__ import annotations

import math

import cast
import effects
import gear
import paths
import reputation
import tuning
from shapes import Npc, State, Thing

PRIOR_RULINGS = 10


def _names(state: State) -> dict[str, str]:
    return {npc["id"]: npc["name"] for npc in state["npcs"]}


def owner_label(state: State, obj: Thing) -> str:
    owner = obj["owner_id"]
    return "nobody" if owner is None else "you" if owner == "player" else _names(state).get(owner, owner)


def walk_costs(state: State) -> dict[str, int]:
    """Steps the player must walk to be within reach of each loose object and person nearby."""
    start = (state["player"]["x"], state["player"]["y"])
    _, far = paths.bfs(start, paths.grid(state), tuning.NEARBY_WALK_STEPS * 2)
    steps = {cell: n for cell, n in far.items() if n <= tuning.NEARBY_WALK_STEPS}

    def cost(x: int, y: int) -> int | None:
        options = [n for cell, n in steps.items() if math.dist(cell, (x, y)) <= tuning.REACH_CELLS]
        return min(options) if options else None

    def to_water(obj: dict) -> int | None:
        """Water spread over an area (a lake, a river) is reached from beside any part of it, and worth a longer
        walk than a loose thing: the user, a short way from the lake, was told there was no water (D-59)."""
        options = [n for cell, n in far.items() if math.dist(cell, cast.nearest(obj, cell)) <= tuning.REACH_CELLS]
        return min(options) if options else None

    costs = {}
    fallen = fallen_holders(state)
    for obj in state["objects"].values():
        if obj["holder_id"] == "player":
            costs[obj["id"]] = 0
        elif obj["holder_id"] in fallen:  # On someone down or dead: reach them to take it (D-49).
            npc = fallen[obj["holder_id"]]
            if cast.distance(start, npc) <= tuning.NEARBY_WALK_STEPS + 3:
                found = cost(npc["x"], npc["y"])
                if found is not None:
                    costs[obj["id"]] = found
        elif obj["holder_id"] is None and obj.get("area"):
            found = to_water(obj)
            if found is not None:
                costs[obj["id"]] = found
        elif obj["holder_id"] is None and cast.distance(start, obj) <= tuning.NEARBY_WALK_STEPS + 3:
            found = cost(obj["x"], obj["y"])
            if found is not None:
                costs[obj["id"]] = found
    for npc in state["npcs"]:
        if cast.distance(start, npc) <= tuning.NEARBY_WALK_STEPS + 3:
            found = cost(npc["x"], npc["y"])
            if found is not None:
                costs[npc["id"]] = found
    return costs


def fallen_holders(state: State) -> dict[str, dict]:
    """People down or dead: what they hold or wear can be taken from them (D-49)."""
    return {n["id"]: n for n in state["npcs"] if n.get("down") or not n.get("alive", True)}


def available_items(state: State, costs: dict | None = None) -> list[dict]:
    """Carried items plus anything intact the player can walk to nearby, whoever owns it (including what someone
    down or dead has on them). A fire put out or burnt out is still there to touch, stir or light again (D-59)."""
    costs = walk_costs(state) if costs is None else costs
    fallen = fallen_holders(state)
    return [
        _on_body(obj, fallen)
        for obj in state["objects"].values()
        if obj["id"] in costs
        and (obj["holder_id"] in (None, "player") or obj["holder_id"] in fallen)
        and "water_source" not in obj["capabilities"]
        and obj["condition"] in ("usable", "installed", "put out", "burnt out")
    ]


def _on_body(obj: Thing, fallen: dict[str, dict]) -> dict:
    """Something on a fallen person is where they lie."""
    npc = fallen.get(obj["holder_id"])
    return {**obj, "x": npc["x"], "y": npc["y"], "on_person": npc["id"]} if npc else obj


def people_nearby(state: State, costs: dict | None = None) -> list[dict]:
    costs = walk_costs(state) if costs is None else costs
    people = []
    for npc in state["npcs"]:
        distance = cast.distance(state["player"], npc)
        if distance <= tuning.PEOPLE_RADIUS:
            health = npc.get("health", 100)
            people.append(
                {
                    "id": npc["id"],
                    "name": npc["name"],
                    "role": npc["role"],
                    "distance_cells": round(distance, 1),
                    "within_reach": distance <= tuning.REACH_CELLS,
                    "walk_steps": costs.get(npc["id"]),
                    "condition": (
                        "dead"
                        if not npc.get("alive", True)
                        else "down (disabled, can't fight)"
                        if npc.get("down")
                        else "unhurt"
                        if health >= 100
                        else "wounded"
                        if health > 30
                        else "badly wounded (near death)"
                    ),
                    "injuries": npc.get("injuries", []),
                    "armour": _worn_words(state, npc),
                    "weapon": _held_words(state, npc),
                    **({"conditions": [gear.describe(c) for c in npc["conditions"]]} if npc.get("conditions") else {}),
                    **({"states": effects.how_they_are(npc)} if effects.how_they_are(npc) else {}),  # D-65
                    "aware_of_you": cast.aware(state, npc),
                    "willing_to_help": reputation.will_help(state, npc),
                    "activity": (npc.get("controller") or {}).get("activity", "standing"),
                }
            )
    return people


def _worn_words(state: State, npc: Npc) -> str:
    """What someone has on, in words, for the judge."""
    names = []
    for slot in gear.BODY_SLOTS:
        obj = gear.worn(state, npc, slot)
        if obj is not None and obj["name"] not in names:
            names.append(obj["name"])
    return ", ".join(names) or "no armour"


def _held_words(state: State, npc: Npc) -> str:
    held = [o["name"] for h in gear.HAND_SLOTS if (o := gear.held(state, npc, h))]
    return ", ".join(dict.fromkeys(held)) or "none"


def _judge_view(state: State, obj: Thing, costs: dict) -> dict:
    return {
        "id": obj["id"],
        "name": obj["name"],
        "kind": obj.get("feature", "item"),
        "walk_steps": costs.get(obj["id"], 0),
        "distance_cells": 0 if obj["holder_id"] == "player" else round(cast.distance(state["player"], obj), 1),
        "description": obj.get("description", ""),
        "materials": obj.get("materials", []),
        "mass_kg": obj["mass_kg"],
        "length_m": obj.get("length_m"),
        "capacity_l": obj.get("capacity_l", 0),
        "water_l": obj.get("water_l", 0),
        "temperature": obj.get("temperature", "cold"),
        "burning": obj.get("burning", False),
        "flags": obj.get("flags", []),
        "attributes": obj.get("attributes", []),
        "connections": obj.get("bound_to", []),
        "revision": obj.get("revision", 0),
        "condition": obj.get("condition"),
        "carried_by_player": obj["holder_id"] == "player",
        "portable": "carry" in obj["capabilities"],
        **({"on_someone_down": obj["on_person"]} if obj.get("on_person") else {}),
        "belongs_to": owner_label(state, obj) + (" (lent to the player)" if obj.get("lent_to") == "player" else ""),
        **({"capacity_l": obj["capacity_l"], "water_l": obj.get("water_l", 0.0)} if obj.get("capacity_l") else {}),
        **({"temperature": obj["temperature"]} if obj.get("temperature", "cold") != "cold" else {}),
        **({"burning": True} if obj.get("burning") else {}),
        **({"installed_in": obj["installed_in"]} if obj.get("installed_in") else {}),
        **({"known_capabilities": obj["known_capabilities"]} if obj.get("known_capabilities") else {}),
    }


def water_sources(state: State, costs: dict) -> list[dict]:
    return [
        {
            "id": o["id"],
            "name": o["name"],
            "water_l": o["water_l"],
            "walk_steps": costs[o["id"]],
            "belongs_to": owner_label(state, o),
        }
        for o in state["objects"].values()
        if "water_source" in o["capabilities"] and o["id"] in costs
    ]


def prior_rulings(state: State) -> list[dict]:
    rulings = [
        {
            "intention": e["text"],
            "action": e.get("action", "make"),
            "outcome": e["category"],
            "reason": e["reason"],
            "made": e.get("made_name"),
            "precedent_key": e.get("precedent_key"),
        }
        for e in state["journal"]
        if e.get("kind") == "craft" and e["category"] != "unresolved"
    ]
    return rulings[-PRIOR_RULINGS:]


def build_context(state: State, text: str, selected_ids: list[str]) -> dict:
    costs = walk_costs(state)
    items = available_items(state, costs)
    people = people_nearby(state, costs)
    known = {o["id"] for o in items} | {p["id"] for p in people}
    return {
        "player_intention": text,
        "highlighted_ids": [i for i in selected_ids if i in known],
        "player_cell": [state["player"]["x"], state["player"]["y"]],
        "available_items": [_judge_view(state, o, costs) for o in items],
        "engine_access": {
            "available_items": "Every listed item can be reached by the engine's automatic walk. A positive walk_steps is time to walk, not a barrier to working on it.",
            "carried_by_player": "These items are already in hand; do not add a pickup prerequisite.",
            "connections": "These are actual attachments. Retained parts belong in an assembly's inputs, materials, mass and appearance.",
        },
        "water_sources": water_sources(state, costs),
        "people_nearby": people,
        "prior_rulings": prior_rulings(state),
        "relevant_precedents": [p for p in (state.get("precedents") or []) if any(i in known for i in p["inputs"])][
            -12:
        ],
        "accepted_commitments": [
            c
            for n in state["npcs"]
            for c in (n.get("mind") or {}).get("commitments", [])
            if c.get("status") == "accepted" and n["id"] in known and c.get("until", 0) > state["sim_time_ms"]
        ],
        "player_abilities": {
            "baseline": state.get("actor_abilities")
            or "An ordinary adult with future knowledge; no magic or supernatural strength. Precision work must be justified by the described method, tools and actual help.",
            "conditions": state["player"].get("conditions", []),
            "states": effects.how_they_are(state["player"]),  # Soaked, tied up... (D-65)
            "health": state["player"].get("health", 100),
            "down": bool(state["player"].get("down")),
        },
    }
