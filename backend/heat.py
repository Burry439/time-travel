"""Things on the clock: heat fading off the fire, fires burning down, and the names that say so (a hot
stone, a burning brand). What kindles a fire is here too."""

from __future__ import annotations

import tuning
from shapes import State, Thing


def can_kindle(things: list[dict]) -> bool:
    """Something already burning, or flint and iron to strike sparks with dry tinder to catch them."""
    if any(t.get("burning") for t in things):
        return True
    flint = any("flint" in " ".join(t.get("materials", [])).lower() or "flint" in t["name"] for t in things)
    iron = any(
        "ferromagnetic" in t.get("flags", []) or "iron" in t.get("materials", []) or "steel" in t.get("materials", [])
        for t in things
    )
    tinder = any("combustible" in t.get("flags", []) and t["mass_kg"] <= 1.0 for t in things)
    return flint and iron and tinder


HEAT_ORDER = ["cold", "warm", "hot", "boiling"]


def display_name(obj: Thing) -> str:
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


def rename(obj: Thing) -> None:
    obj.setdefault("base_name", obj["name"])
    obj["name"] = display_name(obj)


def age_objects(state: State, elapsed_ms: int, now: int) -> dict[str, dict]:
    """Time passing for things (by code, no model): hot things cool back, fires burn down.
    Returns {object_id: changed fields} for the event payload."""
    changes: dict[str, dict] = {}
    end = now + elapsed_ms
    for obj in state.get("objects", {}).values():
        fields = {}
        heat = obj.get("temperature", "cold")
        if heat != "cold" and obj.get("heated_at") is not None:
            level, since = heat, obj["heated_at"]
            while level != "cold" and end - since >= tuning.COOLING_MS[level]:
                since += tuning.COOLING_MS[level]
                level = HEAT_ORDER[HEAT_ORDER.index(level) - 1]
            if level != heat:
                fields.update(temperature=level, heated_at=None if level == "cold" else since)
        if obj.get("burning") and obj.get("burns_until") is not None and end >= obj["burns_until"]:
            fields.update(
                burning=False,
                burns_until=None,
                flags=[f for f in obj.get("flags", []) if f not in ("heat_source", "light_source")],
            )
            if obj.get("feature") == "fire" or obj.get("created_by") == "player" and not obj.get("capacity_l"):
                fields.update(condition="burnt out", description=f"The cold ashes of what was a {obj['name']}.")
        if fields:
            probe = {**obj, **fields}
            probe.setdefault("base_name", obj["name"])
            fields.update(base_name=probe["base_name"], name=display_name(probe))
            changes[obj["id"]] = fields
    return changes
