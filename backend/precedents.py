"""Causal precedent matching; a changed method or changed inputs gets a fresh ruling."""

from __future__ import annotations

import json

FIELDS = (
    "id",
    "materials",
    "mass_kg",
    "flags",
    "attributes",
    "revision",
    "capacity_l",
    "water_l",
    "temperature",
    "burning",
    "condition",
    "known_capabilities",
)


def fingerprint(obj):
    defaults = {
        "capacity_l": 0,
        "water_l": 0,
        "temperature": "cold",
        "burning": False,
        "flags": [],
        "attributes": [],
        "revision": 0,
        "known_capabilities": [],
    }
    return {f: obj.get(f, defaults.get(f)) for f in FIELDS}


# These are reducer arguments, not a list of permitted inventions.
CAUSAL_ARGUMENTS = {
    "new_object": ("consumes", "tools_used", "mass_kg", "length_m", "capacity_l", "rated_load_kg"),
    "transformation": ("target_id", "tools_used"),
    "gather": ("source_id", "tools_used"),
    "harm": ("target_id", "weapon_id", "method", "family", "target_area", "held_seconds"),
    "demonstration": ("object_id", "used_ids"),
    "fill": ("container_id", "source_id", "litres"),
    "change": ("target_id", "temperature", "burning", "heat_source_id", "pour_into_id", "pour_litres"),
    "give": ("item_ids", "recipient_id"),
    "install": ("object_id", "into_id", "aid_ids"),
    "lift_out": ("object_id", "aid_ids"),
    "offer_trade": ("give_ids", "want_ids", "recipient_id"),
    "treat": ("patient_id", "remedy_id", "condition"),
    "equip": ("object_id", "slot"),
}


def mechanism(step):
    signature = {k: step.get(k, []) for k in ("resource_ids", "helper_ids", "take_ids", "effects")}
    for operation, fields in CAUSAL_ARGUMENTS.items():
        args = step.get(operation) or {}
        signature[operation] = {f: args.get(f) for f in fields}
    return signature


def helper_fingerprint(person):
    return {f: person.get(f) for f in ("state", "conditions", "willing_to_help", "armour", "weapon")}


def contradiction(context, result):
    key = result.get("precedent_key")
    if not key or len(result.get("steps", [])) != 1:
        return None
    current = {o["id"]: o for o in context.get("available_items", [])}
    step = result["steps"][0]
    for previous in reversed(context.get("relevant_precedents", [])):
        if previous.get("key") != key or previous["proposal"]["action"] != step["action"]:
            continue
        if not previous["inputs"] or any(
            i not in current or fingerprint(o) != fingerprint(current[i]) for i, o in previous["inputs"].items()
        ):
            continue
        if mechanism(previous["proposal"]) != mechanism(step):
            continue
        people = {p["id"]: p for p in context.get("people_nearby", [])}
        if any(
            i not in people or helper_fingerprint(people[i]) != fingerprint
            for i, fingerprint in previous.get("helpers", {}).items()
        ):
            continue
        if previous["outcome"] != step["outcome"]:
            return json.dumps(previous, ensure_ascii=False)
    return None
