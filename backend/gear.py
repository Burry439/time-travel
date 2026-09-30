"""Gear, blows and bodies (GDD D-49): what things do as weapons, shields, armour and remedies, what a blow does
to a person, and the conditions that follow (bleeding, burns, broken bones, infection, knockouts).

Every number lives in data/content/gear.json and is applied here, by code. The judge only proposes a class for
something made (and, for a described attack, how it lands); nothing here is ever rolled.
"""

from __future__ import annotations

import math

import content

GEAR = content.GEAR
WEAPONS: dict[str, dict] = GEAR["weapons"]
ARMOUR: dict[str, dict] = GEAR["armour"]
SHIELDS: dict[str, dict] = GEAR["shields"]
REMEDIES: dict[str, dict] = GEAR["remedies"]
MATERIALS = GEAR["materials"]
SIT = GEAR["situations"]
COND = GEAR["conditions"]
QUALITY = GEAR["quality"]
KINDS = ("weapon", "shield", "armour", "clothing", "ammo", "remedy", "none")
BODY_SLOTS = ("head", "body", "arms", "legs", "hands", "feet")
HAND_SLOTS = ("right", "left")
SLOTS = BODY_SLOTS + HAND_SLOTS + ("ammo",)
COVERS = BODY_SLOTS + ("neck",)  # A coif or gorget covers the throat; nothing is equipped "on the neck" alone.
AREAS = tuple(SIT["areas"])
FAMILIES = ("blow", "missile", "pour", "choke", "other")
RESULTS = ("missed", "blocked", "deflected", "wounded", "knocked_out", "disabled", "killed")


# --- What a thing is ---------------------------------------------------------------------------------------------


def _materials(obj: dict) -> list[str]:
    return [m.lower() for m in obj.get("materials") or []]


def _has(obj: dict, words: list[str]) -> bool:
    mats = _materials(obj)
    return any(w in m or m in w for m in mats for w in words)


def edge(obj: dict | None) -> tuple[str | None, float]:
    """The hardest cutting or piercing material in a thing, and its hardness (wood 0.5 … steel 3)."""
    if not obj:
        return None, 0.0
    best, hard = None, 0.0
    for material in _materials(obj):
        for name, value in MATERIALS["hardness"].items():
            if name in material and value > hard:
                best, hard = name, value
    return best, hard


def _fits(requires: dict, obj: dict) -> bool:
    flags = set(obj.get("flags") or [])
    length, mass = obj.get("length_m") or 0.0, obj.get("mass_kg") or 0.0
    if requires.get("sharp") and "sharp_edge" not in flags:
        return False
    if requires.get("hard_edge") and edge(obj)[1] < 2.0:
        return False
    if requires.get("rigid") and "rigid" not in flags and not _has(obj, ["stone", "iron", "wood", "bone", "bronze"]):
        return False
    if requires.get("flexible") and "flexible" not in flags and "tieable" not in flags:
        return False
    if requires.get("container") and "container" not in flags:
        return False
    if requires.get("burning") and not obj.get("burning"):
        return False
    for key, value in requires.items():
        if key == "min_length" and length < value or key == "max_length" and length and length > value:
            return False
        if key == "min_mass" and mass < value or key == "max_mass" and mass > value:
            return False
    return True


def valid(proposed: dict | None, obj: dict) -> bool:
    """Does a judged gear class fit the thing's physics? (a sword needs a hard sharp edge, mail needs iron…)"""
    if not proposed or proposed.get("kind") not in KINDS:
        return False
    kind, cls = proposed["kind"], proposed.get("class")
    mass = obj.get("mass_kg") or 0.0
    if kind == "none":
        return True
    if kind == "weapon":
        return cls in WEAPONS and _fits(WEAPONS[cls].get("requires", {}), obj)
    if kind == "shield":
        spec = SHIELDS.get(cls)
        return (
            bool(spec)
            and "rigid" in (obj.get("flags") or [])
            and spec.get("min_mass", 0) <= mass <= spec.get("max_mass", 99)
        )
    if kind in ("armour", "clothing"):
        spec = ARMOUR.get(cls)
        return bool(spec) and _has(obj, spec["materials"]) and mass >= spec.get("min_mass", 0)
    if kind == "ammo":
        return cls in GEAR["ammo"]
    if kind == "remedy":
        spec = REMEDIES.get(cls)
        if not spec:
            return False
        if cls == "stitches":
            return _has(obj, ["iron", "bone", "bronze", "steel", "copper"]) and _has(
                obj, ["thread", "gut", "hair", "fiber", "fibre", "flax", "linen", "sinew", "silk", "wool"]
            )
        if cls == "splint":
            return "rigid" in (obj.get("flags") or []) or _has(obj, ["wood", "bark", "bone"])
        if cls == "tourniquet":
            return (
                "tieable" in (obj.get("flags") or [])
                or "flexible" in (obj.get("flags") or [])
                or _has(obj, ["cord", "rope", "fiber", "leather", "cloth", "linen"])
            )
        if cls == "clean_water":
            return (obj.get("water_l") or 0) > 0 and obj.get("temperature", "cold") in ("hot", "boiling", "warm")
        return _has(obj, spec.get("materials", [])) if spec.get("materials") else True
    return False


def classify(obj: dict) -> dict:
    """Code's own reading of a thing, for anything without a judged class (seed items, older made things)."""
    flags = set(obj.get("flags") or [])
    mass, length = obj.get("mass_kg") or 0.0, obj.get("length_m") or 0.0
    name = (obj.get("base_name") or obj.get("name") or "").lower()
    guesses: list[tuple[str, str]] = []
    for word, guess in (
        ("bandage", ("remedy", "bandage")),
        ("poultice", ("remedy", "poultice")),
        ("salve", ("remedy", "salve")),
        ("splint", ("remedy", "splint")),
        ("helmet", ("armour", "helmet")),
        ("mail", ("armour", "mail")),
        ("shield", ("shield", "round")),
        ("bow", ("weapon", "bow")),
        ("sling", ("weapon", "sling")),
        ("javelin", ("weapon", "javelin")),
        ("sword", ("weapon", "long_sword")),
        ("axe", ("weapon", "hand_axe")),
        ("spear", ("weapon", "short_spear")),
        ("knife", ("weapon", "knife")),
        ("dagger", ("weapon", "knife")),
        ("hammer", ("weapon", "hammer")),
        ("club", ("weapon", "club")),
        ("jerkin", ("armour", "leather")),
        ("gambeson", ("armour", "padded")),
        ("arrow", ("ammo", "arrow")),
        ("cap", ("armour", "cap")),
        ("hood", ("armour", "cap")),
        ("boots", ("clothing", "boots")),
        ("gloves", ("clothing", "gloves")),
    ):
        if word in name:
            guesses.append(guess)
    if obj.get("burning") and length:
        guesses.append(("weapon", "brand"))
    if "container" in flags:
        guesses.append(("weapon", "container"))
    if "sharp_edge" in flags:
        guesses += [
            ("weapon", c)
            for c in ("long_spear", "short_spear", "long_sword", "short_sword", "hand_axe", "knife", "sickle")
        ]
    if length >= 0.4 and ("sharp_edge" in flags or "point" in name or "stake" in name):
        guesses.append(("weapon", "stake"))
    guesses += [("weapon", c) for c in ("staff", "club", "hand_stone")]
    for kind, cls in guesses:
        if valid({"kind": kind, "class": cls}, obj):
            return {"kind": kind, "class": cls, "covers": _covers(kind, cls), "quality": "crude"}
    if mass and mass <= GEAR["thrown"]["max_mass"] and "rigid" in flags:  # Leaves, cloth and cord aren't weapons.
        return {"kind": "weapon", "class": "improvised", "covers": [], "quality": "crude"}
    return {"kind": "none", "class": None, "covers": [], "quality": "fair"}


def _covers(kind: str, cls: str | None) -> list[str]:
    if kind in ("armour", "clothing") and cls in ARMOUR:
        return list(ARMOUR[cls]["slots"])
    return []


# A judged class that doesn't quite fit tries its near kin before code's own reading (a long-hafted flint axe is
# still an axe: a great axe, not a spear).
KIN = {
    "hand_axe": ["great_axe"],
    "great_axe": ["hand_axe"],
    "short_sword": ["long_sword", "knife"],
    "long_sword": ["short_sword", "great_sword"],
    "great_sword": ["long_sword"],
    "knife": ["sickle", "short_sword"],
    "sickle": ["knife"],
    "short_spear": ["long_spear", "stake", "javelin"],
    "long_spear": ["short_spear"],
    "stake": ["short_spear"],
    "javelin": ["short_spear"],
    "club": ["mace", "staff", "hand_stone"],
    "mace": ["club", "hammer"],
    "hammer": ["mace", "club"],
    "staff": ["club"],
    "hand_stone": ["club"],
    "padded": ["thick", "clothes"],
    "thick": ["padded", "clothes"],
    "leather": ["lamellar", "thick"],
    "lamellar": ["leather"],
    "mail": ["scale"],
    "scale": ["mail", "lamellar"],
    "cap": ["helmet"],
    "helmet": ["cap"],
    "round": ["improvised", "large", "buckler"],
    "buckler": ["round", "improvised"],
    "large": ["round", "improvised"],
    "salve": ["poultice"],
    "poultice": ["salve"],
}


def checked(proposed: dict | None, obj: dict, notes: list[str] | None = None) -> dict:
    """A judged gear class if it fits the thing (or its near kin does), else code's own reading (noted)."""
    if proposed and not valid(proposed, obj):
        for kin in KIN.get(proposed.get("class") or "", []):
            if valid({**proposed, "class": kin}, obj):
                if notes is not None:
                    notes.append(f"Gear '{proposed.get('class')}' doesn't fit the thing; its kin '{kin}' does.")
                proposed = {**proposed, "class": kin}
                break
    if valid(proposed, obj):
        covers = [c for c in (proposed.get("covers") or []) if c in COVERS] or _covers(
            proposed["kind"], proposed.get("class")
        )
        return {
            "kind": proposed["kind"],
            "class": proposed.get("class"),
            "covers": covers,
            "quality": proposed.get("quality") if proposed.get("quality") in QUALITY else "fair",
        }
    fallback = classify(obj)
    if proposed and proposed.get("kind") not in (None, "none") and notes is not None:
        notes.append(
            f"Gear '{proposed.get('kind')}:{proposed.get('class')}' doesn't fit the thing; "
            f"read as {fallback['kind']}:{fallback['class']}."
        )
    return fallback


def of(obj: dict | None) -> dict:
    if not obj:
        return {"kind": "none", "class": None, "covers": [], "quality": "fair"}
    return obj.get("gear") or classify(obj)


def weapon(obj: dict | None) -> dict:
    """The fighting profile of what's in a hand (None or a non-weapon: fists, or something swung)."""
    record = of(obj)
    cls = (
        record["class"]
        if record["kind"] == "weapon" and record.get("class") in WEAPONS
        else ("fists" if obj is None else "improvised")
    )
    spec = dict(WEAPONS[cls])
    quality = QUALITY.get(record.get("quality", "fair"), 1.0) if obj else 1.0
    damage_type, damage = spec["type"], float(spec["base"])
    material, hardness = edge(obj)
    if obj is not None and damage_type in ("cut", "pierce"):
        if hardness < 1.0 and damage_type == "cut" or material is None:
            damage_type, damage = "blunt", damage * 0.5  # A wooden "blade" is a club.
        else:
            damage *= MATERIALS["edge"].get(material, 0.5)
    if damage_type == "blunt" and obj is not None:
        ratio = (obj.get("mass_kg") or 0.5) / spec.get("ref_mass", 1.0)
        damage *= max(0.5, min(1.6, math.sqrt(ratio)))
    return {
        "class": cls,
        "name": spec["name"],
        "hands": spec["hands"],
        "type": damage_type,
        "damage": round(damage * quality, 1),
        "reach": spec["reach"],
        "windup_ms": spec["windup_ms"],
        "recover_ms": spec["recover_ms"],
        "animation": spec["animation"],
        "range": spec.get("range"),
        "speed": spec.get("speed"),
        "ammo": spec.get("ammo"),
        "thrown": spec.get("thrown", False),
        "edge_hardness": hardness if damage_type in ("cut", "pierce") else 0.0,
        "mass": (obj or {}).get("mass_kg", 0.5),
        "object_id": (obj or {}).get("id"),
    }


def thrown(obj: dict) -> dict:
    """Anything thrown by hand: a stone, a knife, a pot."""
    spec = weapon(obj)
    if spec["thrown"]:
        return spec
    t = GEAR["thrown"]
    kind = "pierce" if "sharp_edge" in (obj.get("flags") or []) and spec["type"] == "pierce" else "blunt"
    damage = 20.0 * max(0.4, min(1.6, math.sqrt((obj.get("mass_kg") or 0.5) / 1.0)))
    if kind == "pierce":
        damage = spec["damage"] * 0.6
    return {
        **spec,
        "type": kind,
        "damage": round(damage, 1),
        "range": t["range"],
        "speed": t["speed"],
        "windup_ms": t["windup_ms"],
        "recover_ms": t["recover_ms"],
        "animation": "throw",
        "thrown": True,
        "edge_hardness": spec["edge_hardness"] if kind == "pierce" else 0.0,
    }


# --- What a person wears and holds -------------------------------------------------------------------------------


def owner_key(person: dict) -> str:
    return person.get("id", "player")


def equipped(person: dict) -> dict:
    return person.get("equipped") or {}


def worn(state: dict, person: dict, slot: str) -> dict | None:
    """What's in a slot, if the person still has it (taken, dropped or given away, it's simply gone)."""
    oid = equipped(person).get(slot)
    obj = state["objects"].get(oid) if oid else None
    return (
        obj
        if obj is not None and obj.get("holder_id") == owner_key(person) and obj.get("condition") != "broken"
        else None
    )


def held(state: dict, person: dict, hand: str = "right") -> dict | None:
    return worn(state, person, hand)


def weapon_in_hand(state: dict, person: dict) -> dict | None:
    """The weapon in either hand (the right first), if any."""
    for hand in HAND_SLOTS:
        obj = held(state, person, hand)
        if obj is not None and of(obj)["kind"] == "weapon":
            return obj
    return None


def layers(state: dict, person: dict, slot: str) -> list[dict]:
    """The armour profiles covering a body slot, outermost last."""
    found, seen = [], set()
    for key in (k for k in equipped(person) if k in COVERS):
        obj = worn(state, person, key)
        record = of(obj)
        if (
            obj
            and obj["id"] not in seen
            and record["kind"] in ("armour", "clothing")
            and slot in (record.get("covers") or [])
        ):
            seen.add(obj["id"])  # A mail shirt fills the body and arms slots but is one layer.
            found.append(armour_profile(obj, record))
    return found


def armour_profile(obj: dict | None, record: dict) -> dict:
    spec = ARMOUR[record["class"]]
    quality = QUALITY.get(record.get("quality", "fair"), 1.0)
    hardness = spec["hardness"]
    if obj is not None and hardness >= 2.0:  # Metal armour is as hard as its metal.
        metals = [GEAR["metal_armour_hardness"][m] for m in GEAR["metal_armour_hardness"] if _has(obj, [m])]
        hardness = max(metals) if metals else hardness
    return {
        "class": record["class"],
        "cut": min(0.97, spec["cut"] * quality),
        "pierce": min(0.97, spec["pierce"] * quality),
        "blunt": min(0.9, spec["blunt"] * quality),
        "burn": 0.0,
        "hardness": hardness,
    }


def shield_of(state: dict, person: dict) -> dict | None:
    for hand in HAND_SLOTS:
        obj = held(state, person, hand)
        if obj and of(obj)["kind"] == "shield":
            return obj
    return None


# --- A blow ------------------------------------------------------------------------------------------------------


def hit(
    state: dict,
    target: dict,
    attack: dict,
    *,
    area: str = "torso",
    aware: bool = True,
    held_down: bool = False,
    family: str = "blow",
    liquid: dict | None = None,
    held_seconds: int = 0,
    judged: str | None = None,
) -> dict:
    """What a landed attack does to this person: effective damage, the result word and the conditions it leaves.
    attack is a weapon() / thrown() profile. Nothing is changed here; see apply()."""
    area = area if area in AREAS else "torso"
    out = {
        "effective": 0.0,
        "type": attack.get("type", "blunt"),
        "area": area,
        "deflected": False,
        "conditions": [],
        "result": "missed",
        "knockout": False,
        "kill": False,
        "down": False,
    }
    down_already = bool(target.get("down")) or held_down
    if family == "choke":
        if aware and not down_already:
            out["result"] = "missed"  # A choke needs them unaware, down or held (a law).
            return out
        seconds = max(0, int(held_seconds))
        if seconds >= COND["choke_kill_s"]:
            out.update(effective=target.get("health", 100), kill=True, result="killed")
        elif seconds >= COND["choke_out_s"]:
            out.update(effective=5.0, knockout=True, result="knocked_out", down=True)
            out["conditions"].append({"kind": "knocked_out", "area": "neck"})
        else:
            out.update(effective=5.0, result="wounded")
        return out
    if family == "other":
        word = judged if judged in RESULTS else "wounded"
        if aware and not down_already and word in ("killed", "disabled", "knocked_out"):
            word = "wounded"  # Someone alert and on their feet isn't dispatched by a trick alone (a law).
        if attack.get("class") == "fists" and not down_already and word in ("killed", "disabled", "knocked_out"):
            word = "wounded"  # Bare hands on someone standing: a shove or a trip hurts, it doesn't fell (a law).
        effective = {
            "killed": target.get("health", 100),
            "disabled": max(0.0, target.get("health", 100) - 20),
            "knocked_out": 5.0,
            "wounded": 30.0,
        }.get(word, 0.0)
        out.update(
            effective=float(effective),
            result=word,
            kill=word == "killed",
            down=word in ("disabled", "knocked_out"),
            knockout=word == "knocked_out",
        )
        if word == "knocked_out":
            out["conditions"].append({"kind": "knocked_out", "area": area})
        return out
    if family == "pour":
        heat = (liquid or {}).get("temperature", "cold")
        effective = {"boiling": 45.0, "hot": 20.0}.get(heat, 0.0)
        out.update(type="burn", effective=effective, result="wounded" if effective else "missed")  # Cold: soaked.
        if heat == "boiling":
            out.update(down=True, result="disabled")  # Scalded blind: down, alive (D-41 law)...
            out["conditions"].append({"kind": "knocked_out", "area": "head"})  # ...for a while (D-49).
        if effective >= COND["burn_at"]:
            out["conditions"].append({"kind": "burn", "area": "head", "severity": round(effective)})
        return out
    raw = float(attack.get("damage", 0))
    kind = attack.get("type", "blunt")
    raw *= SIT["areas"][area].get(kind, 1.0)
    if down_already:
        raw *= SIT["held_or_down"]
    elif not aware:
        raw *= SIT["unaware"]
    slot = SIT["area_slot"][area]
    worn = layers(state, target, slot)
    hardest = max((layer["hardness"] for layer in worn), default=0.0)
    stop = 1.0 - math.prod(1.0 - layer.get(kind, 0.0) for layer in worn)
    blunt_stop = 1.0 - math.prod(1.0 - layer["blunt"] for layer in worn)
    if attack.get("class") == "fists" and hardest >= 2.0:
        out.update(deflected=True, result="deflected")  # A fist does nothing through metal (D-41).
        return out
    if kind in ("cut", "pierce") and worn and attack.get("edge_hardness", 0.0) <= hardest:
        heavy = attack.get("mass", 0) >= SIT["heavy_blunt_kg"]
        share = 0.5 if heavy else SIT["deflected_blunt_share"]
        effective = raw * share * (1.0 - blunt_stop)
        if not heavy:
            effective = min(effective, SIT["deflected_max"])
        out.update(
            effective=round(effective, 1),
            deflected=True,
            type="blunt",
            result="deflected" if effective < 5 else "wounded",
        )
        kind = "blunt"
    else:
        effective = raw * (1.0 - stop)
        out.update(effective=round(effective, 1), result="wounded" if effective > 0 else "deflected")
    effective = out["effective"]
    if kind in ("cut", "pierce") and effective >= COND["bleed_at"]:
        out["conditions"].append(
            {
                "kind": "bleeding",
                "area": area,
                "severity": round(effective),
                "heavy": effective >= COND["heavy_bleed_at"],
            }
        )
    if kind == "blunt" and area == "head" and effective >= COND["knockout_at"]:
        out.update(knockout=True, down=True)
        out["conditions"].append({"kind": "knocked_out", "area": area})
    if kind == "blunt" and area in ("arm", "leg") and effective >= COND["break_at"]:
        out["conditions"].append({"kind": "broken", "area": area})
    if kind == "burn" and effective >= COND["burn_at"]:
        out["conditions"].append({"kind": "burn", "area": area, "severity": round(effective)})
    if (
        area in ("neck", "heart")
        and kind in ("cut", "pierce")
        and not out["deflected"]
        and (not aware or down_already)
        and effective >= COND["vital_kill_at"]
    ):
        out.update(kill=True, result="killed")  # A clean cut to the throat or a thrust to the heart (a law).
    return out


def apply(target: dict, outcome: dict, now: int) -> str:
    """Carry an outcome out on a person (the stranger or anyone else); returns the final result word."""
    health = float(target.get("health", 100))
    health = 0.0 if outcome.get("kill") else max(0.0, health - outcome.get("effective", 0.0))
    target["health"] = round(health, 1)
    for condition in outcome.get("conditions", []):
        add_condition(target, condition, now)
    if health <= 0:
        target["alive"] = False
        return "killed"
    down = outcome.get("down") or (health <= COND["down_at"] and "id" in target)  # The stranger drops only when
    # knocked out or scalded; people in the world go down at 25 (D-41).
    if down:
        target["down"] = True
    if outcome.get("knockout"):
        return "knocked_out"
    if down and outcome.get("result") not in ("knocked_out",):
        return "disabled"
    return outcome.get("result", "wounded")


# --- Conditions and healing --------------------------------------------------------------------------------------


def conditions(person: dict) -> list[dict]:
    return person.setdefault("conditions", [])


def add_condition(person: dict, condition: dict, now: int) -> None:
    entry = {"kind": condition["kind"], "area": condition.get("area", "torso"), "since": now, "treated": 0}
    if condition["kind"] == "bleeding":
        entry.update(severity=condition.get("severity", 10), heavy=bool(condition.get("heavy")))
    elif condition["kind"] == "burn":
        entry["severity"] = condition.get("severity", 10)
    elif condition["kind"] == "knocked_out":
        entry["until"] = now + COND["knockout_ms"]
        if any(c["kind"] == "knocked_out" for c in conditions(person)):
            return
    elif condition["kind"] == "broken" and any(
        c["kind"] == "broken" and c["area"] == entry["area"] for c in conditions(person)
    ):
        return
    conditions(person).append(entry)


def bleed_rate(condition: dict) -> float:
    """Health lost per simulated minute from one bleeding wound, after whatever treatment it's had."""
    base = condition.get("severity", 10) / COND["bleed_per_min_divisor"]
    treated = condition.get("treated", 0)
    if treated >= 3 or treated >= 1 and not condition.get("heavy") or treated == 2:
        return 0.0
    return base / 4 if treated >= 1 else base


def untreated(person: dict) -> list[dict]:
    """Conditions that still need something (they stop natural healing)."""
    out = []
    for c in conditions(person):
        if (
            c["kind"] == "bleeding"
            and bleed_rate(c) > 0
            or c["kind"] in ("burn", "infection", "broken")
            and not c.get("treated")
        ):
            out.append(c)
    return out


def advance(person: dict, elapsed_ms: int, now: int) -> dict:
    """Bodies over time: bleeding and infection drain, a knockout wears off, open wounds fester, and with nothing
    untreated the body mends. Returns what changed (for the event)."""
    if not person.get("alive", True) or elapsed_ms <= 0:
        return {}
    end = now + elapsed_ms
    health = float(person.get("health", 100))
    before = (health, person.get("down"), len(conditions(person)))
    minutes = elapsed_ms / 60_000
    for c in list(conditions(person)):
        if c["kind"] == "bleeding":
            health -= bleed_rate(c) * minutes
        elif c["kind"] == "infection" and not c.get("treated"):
            health -= elapsed_ms / COND["infection_ms_per_hp"]
        elif c["kind"] == "knocked_out" and end >= c.get("until", 0):
            conditions(person).remove(c)
            if (health > COND["down_at"] or "id" not in person) and not any(
                x["kind"] == "broken" and x["area"] == "leg" for x in conditions(person)
            ):
                person["down"] = False
                person["woke_at"] = end
    open_wounds = [
        c
        for c in conditions(person)
        if c["kind"] in ("bleeding", "burn") and c.get("treated", 0) < 2 and not c.get("clean")
    ]
    if open_wounds and not any(c["kind"] == "infection" for c in conditions(person)):
        oldest = min(c["since"] for c in open_wounds)
        if end - oldest >= COND["infect_after_ms"]:
            conditions(person).append({"kind": "infection", "area": open_wounds[0]["area"], "since": end, "treated": 0})
    if not untreated(person) and health < 100:
        mended = elapsed_ms / COND["heal_ms_per_hp"]
        health = min(100.0, health + mended)
        for c in [c for c in conditions(person) if c["kind"] != "knocked_out"]:
            if c.get("treated") and end - c.get("treated_at", c["since"]) >= _mend_ms(c):
                conditions(person).remove(c)  # Healed: the wound is closed, the bone knit.
    health = max(0.0, health)
    person["health"] = round(health, 2)
    if health <= 0:
        person["alive"] = False
    elif health <= COND["down_at"] and not person.get("down") and "id" in person:
        person["down"] = True
    after = (person["health"], person.get("down"), len(conditions(person)))
    if after == before:
        return {}
    return {
        "health": person["health"],
        "alive": person.get("alive", True),
        "down": bool(person.get("down")),
        "conditions": [dict(c) for c in conditions(person)],
    }


def _mend_ms(condition: dict) -> int:
    return {"broken": 30 * 60_000, "burn": 20 * 60_000, "infection": 15 * 60_000}.get(condition["kind"], 10 * 60_000)


def remedy_for(obj: dict) -> dict | None:
    record = of(obj)
    return REMEDIES.get(record.get("class")) if record["kind"] == "remedy" else None


def treat(person: dict, condition_index: int, obj: dict, now: int) -> dict:
    """Apply a remedy to one condition: {ok, text, consumed}. Code decides whether it fits and how well it works."""
    spec = remedy_for(obj)
    items = conditions(person)
    if spec is None:
        return {"ok": False, "text": f"The {obj['name']} won't treat anything."}
    if not 0 <= condition_index < len(items):
        return {"ok": False, "text": "There's nothing there to treat."}
    condition = items[condition_index]
    strength = spec["treats"].get(condition["kind"])
    cls = of(obj)["class"]
    if not strength:
        return {"ok": False, "text": f"A {spec['name']} does nothing for {describe(condition)}."}
    if spec.get("limb_only") and condition["area"] not in ("arm", "leg"):
        return {"ok": False, "text": "A tourniquet only works on an arm or a leg."}
    quality = of(obj).get("quality", "fair")
    if cls == "bandage" and quality == "crude":
        strength = min(strength, 1)  # Leaves and moss slow bleeding; they don't close a deep cut.
    if cls == "clean_water":
        condition["clean"] = True
    condition["treated"] = max(condition.get("treated", 0), strength)
    condition["treated_at"] = now
    condition["treated_with"] = spec["name"]
    if spec.get("disables_limb"):
        condition["tourniquet"] = True
    return {
        "ok": True,
        "consumed": spec.get("consumed", True),
        "seconds": spec["time_s"],
        "text": f"You treat {describe(condition)} with the {obj['name']}.",
    }


def describe(condition: dict) -> str:
    area = {"arm": "arm", "leg": "leg", "head": "head", "neck": "neck", "heart": "chest", "torso": "side"}.get(
        condition.get("area", "torso"), "side"
    )
    kind = condition["kind"]
    if kind == "bleeding":
        return f"the {'deep ' if condition.get('heavy') else ''}cut on the {area}"
    if kind == "burn":
        return f"the burn on the {area}"
    if kind == "broken":
        return f"the broken {area}"
    if kind == "infection":
        return f"the festering wound on the {area}"
    return "the blow to the head"


def limb_useless(person: dict, limb: str) -> bool:
    """An unsplinted break, or a tourniquet not yet replaced by stitches, takes the limb out of use."""
    for c in conditions(person):
        if c["area"] != limb:
            continue
        if c["kind"] == "broken" and c.get("treated", 0) < 2:
            return True
        if c.get("tourniquet") and c.get("treated", 0) < 3:
            return True
    return False


# --- Plain words for the menus ----------------------------------------------------------------------------------


def words(obj: dict) -> str:
    """How a thing strikes someone who handles it, in plain words (numbers are for developer mode)."""
    record = of(obj)
    if record["kind"] == "weapon":
        spec = weapon(obj)
        deadly = spec["damage"]
        level = "Deadly" if deadly >= 45 else "Dangerous" if deadly >= 28 else "Painful" if deadly >= 12 else "Feeble"
        how = {"cut": "cuts", "pierce": "stabs", "blunt": "clubs", "burn": "burns"}[spec["type"]]
        reach = (
            "reaches far"
            if spec["reach"] >= 2.2
            else "keeps them back a little"
            if spec["reach"] >= 1.7
            else "close work"
        )
        if spec.get("range"):
            reach = f"shoots up to {spec['range']} paces"
        hands = "two hands" if spec["hands"] == 2 else "one hand"
        return f"{level}: {how}, {reach}, {hands}."
    if record["kind"] in ("armour", "clothing"):
        spec = armour_profile(obj, record)
        cuts = (
            "stops cuts well"
            if spec["cut"] >= 0.8
            else "turns some cuts"
            if spec["cut"] >= 0.35
            else "little against a blade"
        )
        blunt = "blunt blows still get through" if spec["blunt"] < 0.4 else "softens blunt blows"
        return f"Worn on the {', '.join(record['covers'])}: {cuts}; {blunt}."
    if record["kind"] == "shield":
        return "A shield: raise it to take blows from the front."
    if record["kind"] == "remedy":
        spec = REMEDIES[record["class"]]
        return f"A {spec['name']}: treats {', '.join(spec['treats'])}."
    if record["kind"] == "ammo":
        return f"Ammunition: {GEAR['ammo'][record['class']]['name']}."
    return ""


# --- Putting things on and taking them off -----------------------------------------------------------------------


def slots_for(obj: dict) -> list[str]:
    """Where a thing can go: anything carried can be held; worn things go where they cover; ammo in its pouch."""
    record = of(obj)
    if record["kind"] in ("armour", "clothing"):
        return list(record.get("covers") or [])
    if record["kind"] == "ammo":
        return ["ammo"]
    return list(HAND_SLOTS)


def equip_seconds(obj: dict, slot: str) -> int:
    record = of(obj)
    if slot in HAND_SLOTS:
        return GEAR["equip_seconds"]["shield" if record["kind"] == "shield" else "weapon"]
    if slot == "ammo":
        return GEAR["equip_seconds"]["ammo"]
    return int(ARMOUR.get(record.get("class"), {}).get("don_s", 10))


def equip(state: dict, person: dict, obj: dict, slot: str | None, fighting: bool = False) -> dict:
    """Put something on (or in a hand), or take it off (slot None). Code only: {ok, reason?, seconds, text}."""
    key = owner_key(person)
    kit = person.setdefault("equipped", {})
    if obj.get("holder_id") != key:
        return {"ok": False, "reason": f"You aren't carrying the {obj['name']}."}
    record = of(obj)
    current = [s for s, oid in kit.items() if oid == obj["id"]]
    if slot is None:
        if not current:
            return {"ok": False, "reason": f"The {obj['name']} isn't on you."}
        if fighting and any(s in BODY_SLOTS for s in current):
            return {"ok": False, "reason": "Not in the middle of a fight."}
        for s in current:
            kit.pop(s)
        seconds = equip_seconds(obj, current[0])
        return {
            "ok": True,
            "seconds": seconds,
            "text": f"You take off the {obj['name']}."
            if current[0] in BODY_SLOTS
            else f"You put away the {obj['name']}.",
        }
    if slot not in slots_for(obj):
        return {"ok": False, "reason": f"The {obj['name']} doesn't go there."}
    if fighting and slot in BODY_SLOTS:
        return {"ok": False, "reason": "There's no time to put that on in a fight."}
    two_handed = record["kind"] == "weapon" and weapon(obj)["hands"] == 2
    if slot in HAND_SLOTS and (slot == "left" or two_handed) and limb_useless(person, "arm"):
        return {"ok": False, "reason": "Your arm is too hurt to hold that."}
    if slot in HAND_SLOTS and obj.get("mass_kg", 0) > 20:
        return {"ok": False, "reason": f"The {obj['name']} is too heavy to hold up."}
    for s in current:  # Moving it from one place to another.
        kit.pop(s)
    freed = []  # What had to be let go of, and why, so the player is told (D-57).
    if slot in HAND_SLOTS:
        right = worn(state, person, "right")
        if two_handed:
            slot = "right"
            freed = [(worn(state, person, hand), f"the {obj['name']} takes both hands") for hand in HAND_SLOTS]
            kit.pop("left", None)  # Both hands on it.
        elif slot == "left" and right is not None and of(right)["kind"] == "weapon" and weapon(right)["hands"] == 2:
            freed = [(right, f"the {right['name']} takes both hands")]
            kit.pop("right", None)  # Can't keep a two-handed weapon ready with something in the other hand.
        else:
            freed = [(worn(state, person, slot), None)]
        kit[slot] = obj["id"]
        if two_handed:
            kit["left"] = obj["id"]
    elif slot == "ammo":
        kit["ammo"] = obj["id"]
    else:
        for covered in record.get("covers") or [slot]:
            kit[covered] = obj["id"]
    seconds = equip_seconds(obj, slot)
    verb = {"right": "take up", "left": "take up", "ammo": "ready"}.get(slot, "put on")
    text = f"You {verb} the {obj['name']}."
    let_go = {}
    for thing, why in freed:
        if thing is not None and thing["id"] != obj["id"] and thing["id"] not in let_go:
            let_go[thing["id"]] = (thing["name"], why)
    for name, why in let_go.values():
        text += f" The {name} goes back in your pack" + (f": {why}." if why else ".")
    return {"ok": True, "seconds": seconds, "text": text}


def swap_hands(state: dict, person: dict) -> dict:
    kit = person.setdefault("equipped", {})
    right, left = worn(state, person, "right"), worn(state, person, "left")
    if right is not None and left is not None and right["id"] == left["id"]:
        return {"ok": False, "reason": "Both hands are on the same thing."}
    if right is not None and limb_useless(person, "arm"):
        return {"ok": False, "reason": "Your arm is too hurt to hold that."}
    kit.pop("right", None)
    kit.pop("left", None)
    if left is not None:
        kit["right"] = left["id"]
    if right is not None:
        kit["left"] = right["id"]
    return {"ok": True, "seconds": GEAR["equip_seconds"]["swap"], "text": "You change hands."}


def worn_mass(state: dict, person: dict) -> float:
    """Worn armour and clothes (not held things): they don't count toward what you can carry, but they're heavy."""
    ids = {oid for s, oid in equipped(person).items() if s in BODY_SLOTS and worn(state, person, s)}
    return round(sum(state["objects"][i]["mass_kg"] for i in ids), 2)
