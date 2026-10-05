"""Try Something: what the judge sees, what code allows, and the committed effects.

Models propose; this module decides what a proposal may change (GDD section 6.2).
Each validator decision is recorded as a note so the developer trace shows why.
Actions: make an object, take items, transform (cut, break, fell) one thing, harm a person.
"""

from __future__ import annotations

import copy
import math

import cast
import effects
import gear
import heat
import judge_view
import m2
import paths
import reputation
import tuning
from shapes import Npc, State

MAX_PIECES = 8
# Flags describing an active state need an input that can cause it. Without one the
# flag becomes an untested capability instead of a physical fact.
ACTIVE_FLAGS = {
    "magnetized": ({"magnet_source", "magnetized"}, "might become magnetic if touched to a real magnet"),
    "magnet_source": ({"magnet_source", "magnetized"}, "might attract iron if it were magnetic"),
    "light_source": ({"light_source", "heat_source"}, "could give light if lit"),
    "heat_source": ({"heat_source"}, "could give heat if lit"),
}


def ruling(category: str, reason: str, notes: list[str], effort: int = 0, **extra) -> dict:
    base = {
        "category": category,
        "reason": reason,
        "effort_seconds": effort,
        "notes": notes,
        "action": "other",
        "consumed_ids": [],
        "tool_ids": [],
        "new_spec": None,
        "take_ids": [],
        "transform": None,
        "harm": None,
        "fill": None,
        "demonstration": None,
        "give": None,
        "install": None,
        "lift_out": None,
        "offer_trade": None,
        "gather": None,
        "treat": None,
        "equip": None,
        "drop_ids": [],
        "property": [],
        "precedent_key": None,
        "walk": [],
        "effects": [],
    }
    base.update(extra)
    return base


def unresolved(notes: list[str], note: str) -> dict:
    return ruling("unresolved", "The attempt could not be resolved. Nothing changed.", notes + [f"Rejected: {note}"])


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


def _checked_flags(
    proposed: list[str], materials: list[str], support: set[str], capabilities: list[dict], notes: list[str]
) -> list[str]:
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


def _property(state: State, ids: list[str], how: str) -> list[dict]:
    return [
        {"id": i, "name": state["objects"][i]["name"], "owner_id": state["objects"][i]["owner_id"], "how": how}
        for i in ids
        if state["objects"][i]["owner_id"] not in (None, "player") and state["objects"][i].get("lent_to") != "player"
    ]  # Lent by its owner: theirs, but not theft.


# Social actions whose details can be missing when the stranger only talked about them ("I need to show it to the
# guards"); a missing payload for a physical action (make, take, ...) stays unresolved, since its reason claims a change.
PAYLOAD = {"demonstrate": "demonstration", "give": "give", "offer_trade": "offer_trade"}


def validate(state: State, judged: dict | None, service_error: str | None = None) -> dict:
    """Turn a judge proposal into what code will actually commit, against the current state."""
    notes: list[str] = []
    if judged is None:
        return ruling("unresolved", service_error or "The judge could not be reached. Nothing changed.", notes)
    action = judged.get("action", "make")
    outcome, reason = judged["outcome"], judged["reason"].strip() or "Nothing happens."
    effort = max(0, min(tuning.MAX_EFFORT_SECONDS, int(judged["effort_seconds"])))
    key = judged.get("precedent_key")
    proposed_change = any(
        judged.get(field)
        for field in (
            "new_object",
            "take_ids",
            "transformation",
            "harm",
            "fill",
            "change",
            "demonstration",
            "give",
            "install",
            "lift_out",
            "offer_trade",
            "effects",
        )
    )
    if outcome != "success" and proposed_change:
        notes.append(f"Ignored proposed changes because outcome is '{outcome}'.")
    if outcome == "needs_clarification":
        return ruling(outcome, judged.get("clarifying_question") or reason, notes, action=action, precedent_key=key)
    if outcome in ("blocked", "unsupported"):
        if effort:
            notes.append(f"Effort {effort}s ignored: '{outcome}' spends no time.")
        return ruling(outcome, reason, notes, action=action, precedent_key=key)
    if outcome == "failed":
        return ruling("failed", reason, notes, max(1, effort), action=action, precedent_key=key)
    said = judged.get("say_instead") or {}
    if said.get("words", "").strip():  # Words typed as a deed: they go to talk (D-65).
        return ruling("say_instead", reason, notes, action="other", precedent_key=key, say_instead=dict(said))
    bound = effects.limited(state["player"], "hands")
    if bound and action not in ("other", "physical"):
        return ruling("blocked", f"You can't use your hands: {bound['name']}.", notes, action=action, precedent_key=key)
    available = {o["id"]: o for o in judge_view.available_items(state)}
    for helper_id in judged.get("helper_ids", []):
        helper = cast.find(state["npcs"], helper_id)
        if helper is None or not reputation.will_help(state, helper):
            return unresolved(notes, "the proposed helper has not committed to this work or is unavailable")
    if effort < 1 and action != "other":
        notes.append("Effort raised to 1 s: doing something takes time.")
    effort = max(1, effort) if action != "other" else effort
    handlers = {
        "physical": _physical,
        "make": _make,
        "take": _take,
        "transform": _transform,
        "harm": _harm,
        "fill": _fill,
        "change": _change,
        "demonstrate": _demonstrate,
        "give": _give,
        "install": _install,
        "lift_out": _lift_out,
        "offer_trade": _offer_trade,
        "gather": _gather,
        "treat": _treat,
        "equip": _equip,
        "drop": _drop,
    }
    if action in PAYLOAD and not judged.get(PAYLOAD[action]):
        # The judge named an action but described nothing for it (e.g. "demonstrate" for words about showing
        # something later): nothing changes, and the judge's reason stands, rather than "could not be resolved" (D-48).
        notes.append(f"action '{action}' without a {PAYLOAD[action]}: nothing changes.")
        action = "other"
    if action not in handlers:  # Nothing a typed action does: its effects (if any) are the whole deed (D-65).
        verdict = ruling("success", reason, notes, effort, action="other", precedent_key=key)
        return _hurt_self(state, judged, available, _with_effects(state, judged, available, verdict))
    # An assembly includes its existing bindings. Account for them before planning the walk.
    if action == "make" and judged.get("new_object"):
        judged = copy.deepcopy(judged)
        spec = judged["new_object"]
        original = _dedupe(spec["consumes"])
        consumes = connected_items(state, original)
        attached = [i for i in consumes if i not in original]
        if attached:
            unavailable = [i for i in attached if i not in available or "carry" not in available[i]["capabilities"]]
            if unavailable:
                return ruling(
                    "blocked",
                    "Something attached to these materials cannot be moved into the assembly.",
                    notes + [f"Attached parts unavailable or fixed: {unavailable}."],
                    action=action,
                    precedent_key=key,
                )
            spec["consumes"] = consumes
            spec["mass_kg"] += sum(available[i]["mass_kg"] for i in attached)
            spec["materials"] = _dedupe(spec["materials"] + [m for i in attached for m in available[i]["materials"]])
            retained = ", ".join(available[i]["name"] for i in attached)
            spec["description"] = f"{spec['description']} Attached parts remain: {retained}."
            notes.append(f"Included existing attached parts, their materials and mass: {attached}.")
    # Things further than arm's reach are reached by walking there first.
    walk = paths.plan_walk(state, _walk_targets(state, action, judged, available))
    if walk is None:
        return ruling(
            "blocked",
            "That's too far away to get to from here.",
            notes + ["Blocked by code: no walkable path within range."],
            action=action,
            precedent_key=key,
        )
    probe = state
    if walk:
        probe = dict(state)
        probe["player"] = {**state["player"], "x": walk[-1][0], "y": walk[-1][1]}
        seconds = math.ceil(len(walk) / tuning.WALK_CELLS_PER_SECOND)
        effort += seconds
        notes.append(f"Walked {len(walk)} cells first ({seconds} s).")
    verdict = handlers[action](probe, judged, available, notes, reason, effort, key)
    if verdict["category"] == "success":
        verdict["walk"] = walk
        verdict = _with_effects(probe, judged, available, verdict)
    return _hurt_self(probe, judged, available, verdict)


def _with_effects(state: State, judged: dict, available: dict, verdict: dict) -> dict:
    """A successful step keeps the effects it proposes, if every one keeps the world's laws (effects.py), and what an
    onlooker sees of it (seen_as). Any action may carry effects, not only physical (D-65: chalk writing on bark and
    water over Bren were "done" and changed nothing)."""
    if verdict["category"] != "success":
        return verdict
    proposed = copy.deepcopy(judged.get("effects") or [])
    own = [
        e
        for e in proposed
        if str(e.get("target_id") or "").startswith("made_by_step_") and e["target_id"] not in available
    ]
    if own:  # Effects on the thing this very step makes (live: a stake "with a pointed end"): part of what's made.
        proposed = [e for e in proposed if e not in own]
        made = verdict.get("new_spec")
        for effect in own:
            facts = (
                _checked_attributes(
                    {"attributes": [effect["attribute"]]}, verdict["consumed_ids"] + verdict["tool_ids"]
                )
                if made is not None and effect["kind"] == "attribute" and effect.get("attribute")
                else None
            )
            if facts:
                made["attributes"] = [a for a in made["attributes"] if a["name"] != facts[0]["name"]] + facts
            else:
                verdict["notes"].append(f"Dropped a {effect['kind']} effect on the thing being made: it's in the make.")
    for effect in proposed:  # Only a real test asserts observed; writing is plainly there to see.
        if (effect.get("attribute") or {}).get("status") == "observed":
            effect["attribute"]["status"] = "expected"
    water = {w["id"]: state["objects"][w["id"]] for w in judge_view.water_sources(state, judge_view.walk_costs(state))}
    ctx = {"available": available, "water": water, "actor_id": "player", "helpers": judged.get("helper_ids", [])}
    problem = effects.check(state, proposed, ctx)
    if problem:
        return unresolved(verdict["notes"], f"an effect breaks a law: {problem}")
    if proposed:
        verdict["effects"] = verdict.get("effects", []) + [e for e in proposed if e not in verdict.get("effects", [])]
        # Someone else's thing eaten, smashed, taken out of a box, written on or shifted: theirs, and how (a witness
        # may call it theft or damage; using isn't taking, D-46).
        claims: dict[str, str] = {}
        for effect in proposed:  # The gravest thing done to each (moved, then smashed: smashed).
            roles = [("target", effect.get("target_id")), ("other", effect.get("other_id"))]
            roles += [("ids", i) for i in effect.get("ids") or []]
            for role, thing_id in roles:
                how = EFFECT_PROPERTY.get((effect["kind"], role), "used" if role == "target" else None)
                if how and (thing_id in available or thing_id in water):
                    if GRAVITY.index(how) < GRAVITY.index(claims.get(thing_id, "used")) or thing_id not in claims:
                        claims[thing_id] = how
        # An effect's claim replaces the action's own when it's graver (live: a bowl smashed was only "used").
        kept = [
            c
            for c in verdict.get("property", [])
            if c["id"] not in claims
            or GRAVITY.index(c["how"] if c["how"] in GRAVITY else "used") <= GRAVITY.index(claims[c["id"]])
        ]
        held = {c["id"] for c in kept}
        verdict["property"] = kept + [
            c
            for how in dict.fromkeys(claims.values())
            for c in _property(state, [i for i, h in claims.items() if h == how and i not in held], how)
        ]
    if (judged.get("seen_as") or "").strip():
        verdict["seen_as"] = " ".join(judged["seen_as"].split())[:300]
    return verdict


# What an effect does to someone else's thing, for its owner and witnesses: (kind, target or other) -> how. Anything
# else an effect touches as its target is "used"; a thing named as other_id is untouched unless listed.
EFFECT_PROPERTY = {
    ("consume", "target"): "used up",
    ("destroy", "target"): "destroyed",
    ("damage", "target"): "damaged",
    ("take_out", "target"): "taken",
    ("hide", "target"): "hid",
    ("contaminate", "target"): "fouled",
    ("mix", "other"): "used up",
    ("seal", "other"): "used up",
    ("soak", "other"): "used",
    ("put_in", "other"): "used",
    ("disguise", "other"): "used",
    ("build", "ids"): "used up",
    ("trap", "ids"): "used up",
}
GRAVITY = ("destroyed", "damaged", "used up", "taken", "hid", "fouled", "used")


def connected_items(state: State, ids: list[str]) -> list[str]:
    """The whole assembly, including old one-sided links; no recipe or inferred connection."""
    connected = _dedupe(ids)
    for item_id in connected:
        obj = state["objects"].get(item_id)
        if obj is None:
            continue
        partners = set(obj.get("bound_to", [])) | {
            o["id"] for o in state["objects"].values() if item_id in o.get("bound_to", [])
        }
        connected.extend(i for i in sorted(partners) if i not in connected)
    return connected


def _hurt_self(state: State, judged: dict, available: dict, verdict: dict) -> dict:
    """What the stranger's own step does to their body (D-59): theirs to do, never refused for it. Code checks the
    cause is real and at hand: a burn needs something burning or hot now (a hand in a fire that's out burns nobody),
    and a hand put into something a few steps off walks there first."""
    plan = judged.get("hurts_you")
    if not plan or verdict["category"] != "success":
        return verdict
    cause = available.get(plan.get("cause_id") or "")
    if cause is None:
        verdict["notes"].append("Ignored hurts_you: its cause isn't here.")
        return verdict
    if plan["condition"] == "burn" and not (cause.get("burning") or cause.get("temperature") in ("hot", "boiling")):
        verdict["notes"].append(f"Ignored hurts_you: the {cause['name']} isn't hot enough to burn.")
        return verdict
    far = cause["holder_id"] != "player" and cast.distance(state["player"], cause) > tuning.REACH_CELLS
    if far and not verdict.get("walk"):
        walk = paths.plan_walk(state, [(cause["x"], cause["y"])])
        if not walk:
            verdict["notes"].append(f"Ignored hurts_you: the {cause['name']} can't be reached.")
            return verdict
        verdict["walk"] = walk
        verdict["effort_seconds"] += math.ceil(len(walk) / tuning.WALK_CELLS_PER_SECOND)
    wound = {"kind": plan["condition"], "area": plan["area"], "severity": tuning.SELF_HURT[plan["severity"]]}
    body = copy.deepcopy(state["player"])
    gear.add_condition(body, wound, state["sim_time_ms"])
    body["health"] = max(1, body.get("health", 100) - wound["severity"])
    verdict["hurt_self"] = {"conditions": body["conditions"], "health": body["health"], **wound}
    return verdict


def _walk_targets(state: State, action: str, judged: dict, available: dict) -> list[tuple[int, int]]:
    """Cells the player must be within reach of for this step, in no particular order."""
    ids: list[str] = []
    plan = judged.get("new_object") or {}
    if action == "make":
        ids = plan.get("consumes", []) + plan.get("tools_used", [])
    elif action == "take":
        ids = judged.get("take_ids") or []
    elif action == "gather" and judged.get("gather"):
        ids = [judged["gather"]["source_id"]] + judged["gather"]["tools_used"]
    elif action == "transform" and judged.get("transformation"):
        ids = [judged["transformation"]["target_id"]] + judged["transformation"]["tools_used"]
    elif action == "fill" and judged.get("fill"):
        ids = [judged["fill"]["container_id"]]
    elif action == "install" and judged.get("install"):
        ids = [judged["install"]["object_id"], judged["install"]["into_id"]] + judged["install"]["aid_ids"]
    elif action == "lift_out" and judged.get("lift_out"):
        ids = [judged["lift_out"]["object_id"]] + judged["lift_out"]["aid_ids"]
    elif action == "demonstrate" and judged.get("demonstration"):
        ids = [judged["demonstration"]["object_id"]] + judged["demonstration"]["used_ids"]
    harm = judged.get("harm") if action == "harm" else None
    if harm and harm.get("method", "melee") != "thrown" and harm.get("weapon_id"):
        ids = [harm["weapon_id"]]
    deed = judged.get("effects") or []  # Whatever its effects work on: walk there first (D-65).
    ids += judged.get("resource_ids", []) + [
        i for e in deed for i in (e.get("target_id"), e.get("other_id"), *(e.get("ids") or [])) if i
    ]
    cells = [
        (available[i]["x"], available[i]["y"])
        for i in _dedupe(ids)
        if i in available and available[i]["holder_id"] != "player"
    ]
    here = state["player"]
    source = state["objects"].get((judged.get("fill") or {}).get("source_id") or "") if action == "fill" else None
    if source is not None:
        cells.append(cast.nearest(source, here))
    for i in _dedupe([i for e in deed for i in (e.get("target_id"), e.get("other_id")) if i]):
        someone = cast.find(state["npcs"], i)
        water = state["objects"].get(i)
        if someone is not None and someone.get("alive", True):
            cells.append((someone["x"], someone["y"]))
        elif water is not None and "water_source" in water["capabilities"]:
            cells.append(cast.nearest(water, here))
    if action == "demonstrate":  # Showing something in a trough or other water source: go to it.
        cells += [
            cast.nearest(o, here) for i in ids if (o := state["objects"].get(i)) and "water_source" in o["capabilities"]
        ]
    recipient = (
        (judged.get("give") or {}).get("recipient_id")
        if action == "give"
        else (judged.get("offer_trade") or {}).get("recipient_id")
        if action == "offer_trade"
        else None
    )
    npc = next((n for n in state["npcs"] if n["id"] == recipient), None) if recipient else None
    if npc is not None:
        cells.append((npc["x"], npc["y"]))
    if harm and harm.get("method", "melee") != "thrown":
        npc = next((n for n in state["npcs"] if n["id"] == harm["target_id"]), None)
        if npc is not None:
            cells.append((npc["x"], npc["y"]))
    return cells


def _water_at_hand(state: State, thing_id: str) -> bool:
    """A water source within reach (a trough, the lake's edge): something to soak or wet a thing in as it's made."""
    thing = state["objects"].get(thing_id) or {}
    here = state["player"]
    return "water_source" in thing.get("capabilities", []) and cast.distance(here, cast.nearest(thing, here)) <= (
        tuning.REACH_CELLS + 1
    )


def _water_draws(state, available, tools, sources, extra_kg) -> list[dict] | None:
    """Water at hand that goes into what's made (a poultice wetted from the pot, clay worked wet): the mass beyond
    the solid inputs, at most what's really there, drawn from containers first (D-63: a poultice crushed "with a
    splash of water from the pot" was refused for weighing more than its leaves). [{id, litres}], [] if nothing is
    needed, None if there isn't water enough."""
    if extra_kg <= 0.001:
        return []
    draws, left = [], extra_kg
    for thing_id in [i for i in tools if available[i].get("water_l", 0.0) > 0] + list(sources):
        held = state["objects"][thing_id].get("water_l", 0.0)
        litres = min(left, held if held > 0 else tuning.WATER_SCOOP_L)
        if litres > 0:
            draws.append({"id": thing_id, "litres": round(litres, 3)})
            left -= litres
        if left <= 0.001:
            return draws
    return None


def _make(state, judged, available, notes, reason, effort, key) -> dict:
    spec = judged.get("new_object")
    if not spec:
        return unresolved(notes, "action 'make' without a new_object")
    consumes = _dedupe(spec["consumes"])
    tools = [i for i in _dedupe(spec["tools_used"]) if i not in consumes]
    water = [i for i in tools if _water_at_hand(state, i)]  # Soaked, wetted or quenched in it (D-59: the trough).
    tools = [i for i in tools if i not in water]
    missing = [i for i in consumes + tools if i not in available]
    if missing:
        return unresolved(notes, f"proposal used items that are not available now: {missing}")
    if not consumes:
        return unresolved(notes, "a new object must be made from at least one consumed item")
    fixed = [i for i in consumes if "carry" not in available[i]["capabilities"]]
    if fixed:
        return unresolved(notes, f"{fixed} cannot be built into an object without being cut up first")
    for item_id in consumes:
        partners = set(state["objects"][item_id]["bound_to"]) | {
            o["id"] for o in state["objects"].values() if item_id in o["bound_to"]
        }
        if not partners <= set(consumes):
            return unresolved(
                notes, f"{item_id} is tied to {sorted(partners - set(consumes))}, which is not part of the new object"
            )
    input_materials = {m.lower() for i in consumes for m in available[i].get("materials", [])}
    materials = _checked_materials(spec["materials"], input_materials, notes)
    input_mass = round(sum(available[i]["mass_kg"] for i in consumes), 3)
    mass = float(spec["mass_kg"])
    draws = _water_draws(state, available, tools, water, mass - input_mass) if math.isfinite(mass) else None
    if not math.isfinite(mass) or mass <= 0 or (mass > input_mass + 0.001 and draws is None):
        return unresolved(notes, f"output mass {mass} kg contradicts the {input_mass} kg of available material")
    for field in ("length_m", "capacity_l", "rated_load_kg"):
        value = spec.get(field)
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
            return unresolved(notes, f"invalid physical quantity {field}")
    if any(f in spec["flags"] for f in ("magnetized", "ferromagnetic", "magnet_source")) and not {
        "iron",
        "steel",
        "magnetite",
        "lodestone",
    }.intersection(materials):
        return unresolved(notes, "the proposed magnetic property contradicts the non-ferromagnetic material")
    capabilities = [dict(c) for c in spec["capabilities"]]
    support = {
        f
        for i in consumes + tools
        for f in available[i].get("flags", [])
        if f not in ("heat_source", "light_source") or available[i].get("burning")
    }
    if heat.can_kindle([available[i] for i in consumes + tools]):  # Sparks into tinder: a real way to make fire.
        support |= {"heat_source", "light_source"}
    flags = _checked_flags(spec["flags"], materials, support, capabilities, notes)
    capacity = spec.get("capacity_l")
    if capacity and "container" not in flags:
        notes.append("Dropped capacity_l: the object is not flagged as a container.")
        capacity = None
    attributes = _checked_attributes(
        spec, consumes + tools + list(available)
    )  # The fire that heated it is a cause too (D-67).
    if attributes is None:
        return unresolved(notes, "physical attributes need bounded values, real resources and unprotected names")
    new_spec = {
        "name": spec["name"].strip().lower()[:60] or "made thing",
        "description": spec["description"].strip()[:400],
        "materials": materials,
        "mass_kg": round(mass, 3),
        "length_m": _positive(spec.get("length_m")),
        "capacity_l": _positive(capacity),
        "rated_load_kg": _positive(spec.get("rated_load_kg")),
        "flags": flags,
        "known_capabilities": capabilities[:6],
        "attributes": attributes,
        **({"burning": True} if "heat_source" in flags else {}),
    }  # Made alight: a fire.
    new_spec["gear"] = gear.checked(_gear_proposal(spec.get("gear")), new_spec, notes)
    tools_not_ours = [i for i in tools if available[i]["holder_id"] != "player"]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="make",
        consumed_ids=consumes,
        tool_ids=tools,
        new_spec=new_spec,
        precedent_key=key,
        property=_property(state, consumes, "used up") + _property(state, tools_not_ours, "used"),
        water_draws=draws or [],
    )


def _change(state, judged, available, notes, reason, effort, key) -> dict:
    """A thing changes in place (heat, cool, set alight, put out, pour). The judge says what; code keeps the laws:
    heat and flame only from something really burning within reach, water conserved, time enough to boil."""
    plan = judged.get("change")
    if not plan:
        return unresolved(notes, "action 'change' without a change")
    target = available.get(plan["target_id"])
    if target is None:
        return unresolved(notes, f"the thing to change is not within reach: {plan['target_id']}")
    fields: dict = {}
    source = available.get(plan.get("heat_source_id") or "") or state["objects"].get(plan.get("heat_source_id") or "")
    lit = (
        source is not None
        and source.get("burning")
        and cast.distance(state["player"], source) <= tuning.REACH_CELLS + 1
    )
    temperature = plan.get("temperature")
    if temperature and heat.HEAT_ORDER.index(temperature) > heat.HEAT_ORDER.index(target.get("temperature", "cold")):
        if not lit:
            return ruling(
                "blocked",
                f"There's nothing burning here to heat the {target['name']} with.",
                notes + ["Blocked by code: heat needs something burning within reach."],
                action="change",
                precedent_key=key,
            )
        needed = 60 + int(240 * max(0.2, target.get("water_l", 0.0))) if temperature == "boiling" else 30
        if effort < needed:
            notes.append(f"Effort raised to {needed} s: water takes time to heat.")
            effort = needed
    if temperature:
        fields.update(
            temperature=temperature, heated_at=state["sim_time_ms"] + effort * 1000 if temperature != "cold" else None
        )
    if plan.get("burning") is True and not target.get("burning"):
        if not lit:
            return ruling(
                "blocked",
                f"You have no flame to light the {target['name']} with.",
                notes + ["Blocked by code: nothing burning within reach."],
                action="change",
                precedent_key=key,
            )
        if "combustible" not in target.get("flags", []):
            return ruling(
                "failed",
                f"The {target['name']} won't catch fire.",
                notes,
                max(1, effort),
                action="change",
                precedent_key=key,
            )
        span = max(
            tuning.FIRE_MS_RANGE[0], min(tuning.FIRE_MS_RANGE[1], int(target["mass_kg"] * tuning.FIRE_MS_PER_KG))
        )
        fields.update(
            burning=True,
            burns_until=state["sim_time_ms"] + effort * 1000 + span,
            flags=_dedupe(target.get("flags", []) + ["heat_source", "light_source"]),
        )
        if target.get("condition") == "put out":  # Lit again: a fire once more, as it looks and as it reads.
            fields.update(condition="usable", description=f"A {target.get('base_name', target['name'])}, alight.")
    elif plan.get("burning") is False and target.get("burning"):
        fields.update(
            burning=False,
            burns_until=None,
            flags=[f for f in target.get("flags", []) if f not in ("heat_source", "light_source")],
        )
        if target.get("feature") == "fire" or target.get("created_by") == "player" and not target.get("capacity_l"):
            # Put out, it is out: it looks and reads so (the user found "flames licking" on a doused fire, D-59),
            # and it is still warm for a while.
            name = target.get("base_name", target["name"])
            fields.update(
                condition="put out",
                description=f"A {name}, put out: wet, blackened wood and ash, still warm.",
                temperature="warm",
                heated_at=state["sim_time_ms"] + effort * 1000,
            )
    pour = []
    litres = float(plan.get("pour_litres") or 0.0)
    if litres > 0:
        held = target.get("water_l", 0.0)
        litres = round(min(litres, held), 3)
        into = available.get(plan.get("pour_into_id") or "")
        if into is not None:
            room = round((into.get("capacity_l") or 0.0) - into.get("water_l", 0.0), 3)
            litres = min(litres, max(0.0, room))
            pour.append(
                {
                    "id": into["id"],
                    "water_l": round(into.get("water_l", 0.0) + litres, 3),
                    "temperature": target.get("temperature", "cold"),
                    "heated_at": target.get("heated_at"),
                }
            )
        fields["water_l"] = round(held - litres, 3)
    if not fields and not pour:
        return ruling("success", reason, notes, effort, action="other", precedent_key=key)
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="change",
        precedent_key=key,
        change={
            "id": target["id"],
            "fields": fields,
            "pour": pour,
            "spilled_l": round(litres, 3) if litres > 0 and not pour else 0.0,
        },
        property=_property(state, [target["id"]], "used"),
    )


def quick(state: State, verb: str, object_id: str) -> dict:
    """A judge-shaped proposal for the deterministic quick actions (E to pick up, Put down): no model involved."""
    obj = state["objects"].get(object_id)
    if obj is None:
        return {
            "clarifying_question": None,
            "precedent_key": f"quick:{verb}",
            "steps": [
                {
                    "action": "other",
                    "outcome": "blocked",
                    "reason": "There's nothing like that here.",
                    "effort_seconds": 0,
                    "new_object": None,
                    "take_ids": [],
                    "transformation": None,
                    "harm": None,
                }
            ],
        }
    step = {
        "action": verb,
        "outcome": "success",
        "effort_seconds": 2,
        "new_object": None,
        "transformation": None,
        "harm": None,
        "take_ids": [object_id] if verb == "take" else [],
        "drop_ids": [object_id] if verb == "drop" else [],
        "reason": f"You pick up the {obj['name']}." if verb == "take" else f"You put down the {obj['name']}.",
    }
    return {"clarifying_question": None, "precedent_key": f"quick:{verb}", "steps": [step]}


def _drop(state, judged, available, notes, reason, effort, key) -> dict:
    ids = [i for i in _dedupe(judged.get("drop_ids") or []) if state["objects"].get(i, {}).get("holder_id") == "player"]
    if not ids:
        return ruling("blocked", "You aren't carrying that.", notes, action="drop", precedent_key=key)
    return ruling("success", reason, notes, effort, action="drop", precedent_key=key, drop_ids=ids)


def _take(state, judged, available, notes, reason, effort, key) -> dict:
    ids = _dedupe(judged.get("take_ids") or [])
    if not ids:
        return unresolved(notes, "action 'take' without take_ids")
    missing = [i for i in ids if i not in available]
    if missing:
        return unresolved(notes, f"cannot take items that are not within reach: {missing}")
    carried = [i for i in ids if available[i]["holder_id"] == "player"]
    ids = [i for i in ids if i not in carried]
    if carried:
        notes.append(f"Already carried, skipped: {carried}.")
    if not ids:
        return ruling("blocked", "You are already carrying that.", notes, action="take", precedent_key=key)
    fixed = [available[i]["name"] for i in ids if "carry" not in available[i]["capabilities"]]
    if fixed:
        return ruling(
            "blocked",
            f"The {fixed[0]} can't be picked up and carried.",
            notes + [f"Blocked by code: not portable {fixed}."],
            action="take",
            precedent_key=key,
        )
    load = m2.inventory_mass(state) + sum(available[i]["mass_kg"] + available[i]["water_l"] for i in ids)
    if load > tuning.CARRY_LIMIT_KG:
        return ruling(
            "blocked",
            f"That would be more than you can carry ({load:.1f} of {tuning.CARRY_LIMIT_KG:.0f} kg).",
            notes,
            action="take",
            precedent_key=key,
        )
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="take",
        take_ids=ids,
        precedent_key=key,
        property=_property(state, ids, "taken"),
    )


LIVING_PARTS = {"leaf", "bark", "resin", "wood"}  # What a living tree or sapling also gives.


def _gather(state, judged, available, notes, reason, effort, key) -> dict:
    """A small part off something larger that stays where it is: a leaf off a tree, a handful of clay (D-48)."""
    plan = judged.get("gather")
    if not plan:
        return unresolved(notes, "action 'gather' without a gather")
    source = available.get(plan["source_id"])
    if source is None:
        return unresolved(notes, f"gather source is not within reach: {plan['source_id']}")
    tools = [i for i in _dedupe(plan["tools_used"]) if i != source["id"]]
    missing = [i for i in tools if i not in available]
    if missing:
        return unresolved(notes, f"gather used tools that are not available now: {missing}")
    piece = plan["piece"]
    allowed = {m.lower() for m in source.get("materials", [])}
    if source.get("feature") == "tree" or "sapling" in source["name"]:
        allowed |= LIVING_PARTS
    elif "wood" in allowed:
        allowed.add("bark")
    capabilities = [dict(c) for c in piece["capabilities"]]
    fits = [m for m in piece["materials"] if _material_matches(m.lower().strip(), allowed)]
    materials = _checked_materials(
        fits or piece["materials"],
        allowed if fits else {m.lower() for m in source.get("materials", [])} or allowed,
        notes,
    )
    count = max(1, min(MAX_PIECES, int(piece["count"])))
    each = float(piece["mass_kg"])
    cap = min(tuning.GATHER_MAX_KG, source["mass_kg"] / 2)
    if not math.isfinite(each) or each <= 0 or each * count > cap:
        return unresolved(notes, "gathered mass must be finite, positive and a small part of the source")
    attributes = _checked_attributes(piece, [source["id"]] + tools)
    if attributes is None:
        return unresolved(notes, "gathered attributes need real causal resources and unprotected names")
    if m2.inventory_mass(state) + each * count > tuning.CARRY_LIMIT_KG:
        return ruling("blocked", "You can't carry any more.", notes, action="gather", precedent_key=key)
    support = {f for i in [source["id"]] + tools for f in available[i].get("flags", [])}
    spec = {
        "name": piece["name"].strip().lower()[:60] or "piece",
        "description": piece["description"].strip()[:400],
        "materials": materials,
        "count": count,
        "mass_kg": round(each, 3),
        "length_m": _positive(piece.get("length_m")),
        "capacity_l": None,
        "rated_load_kg": None,
        "flags": _checked_flags(piece["flags"], materials, support, capabilities, notes),
        "known_capabilities": capabilities[:4],
        "attributes": attributes,
    }
    spec["gear"] = gear.checked(_gear_proposal(piece.get("gear")), spec, notes)
    tools_not_ours = [i for i in tools if available[i]["holder_id"] != "player"]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="gather",
        tool_ids=tools,
        gather={"source_id": source["id"], "piece": spec},
        precedent_key=key,
        property=_property(state, [source["id"]], "gathered from") + _property(state, tools_not_ours, "used"),
    )


def _patient(state: State, patient_id: str) -> dict | None:
    if patient_id in ("player", "stranger", None):
        return state["player"]
    return next((n for n in state["npcs"] if n["id"] == patient_id), None)


def _treat(state, judged, available, notes, reason, effort, key) -> dict:
    """A remedy on a condition (D-49): code checks the thing fits the condition and how well it works."""
    plan = judged.get("treat")
    if not plan:
        return unresolved(notes, "action 'treat' without a treat")
    remedy = available.get(plan["remedy_id"])
    if remedy is None or remedy["holder_id"] != "player":
        return ruling("blocked", "You don't have that with you.", notes, action="treat", precedent_key=key)
    patient = _patient(state, plan.get("patient_id"))
    if patient is None or not patient.get("alive", True):
        return ruling("blocked", "There's nobody there to treat.", notes, action="treat", precedent_key=key)
    if patient is not state["player"] and cast.distance(state["player"], patient) > tuning.REACH_CELLS:
        return ruling("blocked", f"{patient['name']} is too far away.", notes, action="treat", precedent_key=key)
    items = patient.get("conditions") or []
    index = next(
        (
            i
            for i, c in enumerate(items)
            if c["kind"] == plan["condition"] and c["kind"] != "knocked_out" and (c.get("treated", 0) < 3)
        ),
        None,
    )
    if index is None:
        who = "You have" if patient is state["player"] else f"{patient['name']} has"
        return ruling(
            "blocked",
            f"{who} no {plan['condition'].replace('broken', 'broken bone')} to treat.",
            notes,
            action="treat",
            precedent_key=key,
        )
    probe = copy.deepcopy(patient)
    remedy_view = {**remedy, "gear": gear.checked(remedy.get("gear") or gear.classify(remedy), remedy)}
    result = gear.treat(probe, index, remedy_view, state["sim_time_ms"])
    if not result["ok"]:
        return ruling("failed", result["text"], notes, max(1, effort), action="treat", precedent_key=key)
    effort = max(effort, result["seconds"])
    treat = {
        "patient_id": "player" if patient is state["player"] else patient["id"],
        "patient_name": "you" if patient is state["player"] else patient["name"],
        "conditions": probe["conditions"],
        "remedy_id": remedy["id"],
        "remedy": gear.REMEDIES[remedy_view["gear"]["class"]]["name"],
        "what": gear.describe(items[index]).removeprefix("the "),
        "consumed": remedy["id"] if result["consumed"] else None,
    }
    return ruling("success", reason, notes, effort, action="treat", treat=treat, precedent_key=key)


def _equip(state, judged, available, notes, reason, effort, key) -> dict:
    """Putting something on or in a hand, described in words (the same rules as the pack, D-49)."""
    plan = judged.get("equip")
    if not plan:
        return unresolved(notes, "action 'equip' without an equip")
    obj = available.get(plan["object_id"])
    if obj is None or obj["holder_id"] != "player":
        return ruling("blocked", "You aren't carrying that.", notes, action="equip", precedent_key=key)
    probe = {
        "equipped": dict(state["player"].get("equipped") or {}),
        "conditions": state["player"].get("conditions") or [],
    }
    result = gear.equip(state, probe, obj, plan.get("slot"), fighting=bool(state.get("fight")))
    if not result["ok"]:
        return ruling("blocked", result["reason"], notes, action="equip", precedent_key=key)
    return ruling(
        "success",
        reason or result["text"],
        notes,
        max(effort, result["seconds"]),
        action="equip",
        equip={"equipped": probe["equipped"], "object_id": obj["id"], "slot": plan.get("slot")},
        precedent_key=key,
    )


def _piece_capacity(piece: dict, mass: float, notes: list[str]) -> float | None:
    """What a piece holds, if it's a container: finite, and no more than a thin-walled vessel of its weight could."""
    capacity = piece.get("capacity_l")
    if not capacity:
        return None
    if "container" not in piece.get("flags", []):
        notes.append(f"Dropped capacity_l of '{piece['name']}': it is not flagged as a container.")
        return None
    capacity = float(capacity)
    if not math.isfinite(capacity) or capacity <= 0:
        return None
    most = round(tuning.CONTAINER_L_PER_KG * mass + 0.5, 2)
    if capacity > most:
        notes.append(f"Capacity of '{piece['name']}' cut from {capacity} to {most} L for its weight.")
        capacity = most
    return capacity


def _transform(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("transformation")
    if not plan:
        return unresolved(notes, "action 'transform' without a transformation")
    target_id = plan["target_id"]
    if target_id not in available:
        return unresolved(notes, f"transform target is not within reach: {target_id}")
    target = available[target_id]
    if state["objects"][target_id]["bound_to"] or any(target_id in o["bound_to"] for o in state["objects"].values()):
        return unresolved(notes, f"{target_id} is tied to something; untie it first")
    tools = [i for i in _dedupe(plan["tools_used"]) if i != target_id]
    missing = [i for i in tools if i not in available]
    if missing:
        return unresolved(notes, f"transform used tools that are not available now: {missing}")
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
        mass = float(piece["mass_kg"])
        if not math.isfinite(mass) or mass <= 0:
            return unresolved(notes, "transformed mass must be finite and positive")
        attributes = _checked_attributes(piece, [target_id] + tools)
        if attributes is None:
            return unresolved(notes, "transformed attributes need real causal resources and unprotected names")
        made = {
            "name": piece["name"].strip().lower()[:60] or "piece",
            "description": piece["description"].strip()[:400],
            "materials": materials,
            "count": count,
            "mass_kg": mass,
            "length_m": _positive(piece.get("length_m")),
            "capacity_l": _piece_capacity(piece, mass, notes),  # A gourd cut into a bowl holds water (D-63).
            "flags": _checked_flags(piece["flags"], materials, support, capabilities, notes),
            "known_capabilities": capabilities[:4],
            "attributes": attributes,
        }
        made["gear"] = gear.checked(_gear_proposal(piece.get("gear")), made, notes)
        pieces.append(made)
    if not pieces:
        return unresolved(notes, "transform produced no pieces")
    produced = sum(p["mass_kg"] * p["count"] for p in pieces)
    if produced > target["mass_kg"] + 0.001:
        return unresolved(notes, "transformed pieces cannot contain more mass than the target")
    transform = {"target_id": target_id, "result_state": plan["result_state"], "pieces": pieces}
    tools_not_ours = [i for i in tools if available[i]["holder_id"] != "player"]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="transform",
        tool_ids=tools,
        transform=transform,
        precedent_key=key,
        property=_property(state, [target_id], plan["result_state"]) + _property(state, tools_not_ours, "used"),
    )


def _harm(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("harm")
    if not plan:
        return unresolved(notes, "action 'harm' without a harm")
    npc = next((n for n in state["npcs"] if n["id"] == plan["target_id"]), None)
    if npc is None:
        return unresolved(notes, f"harm target is not a person: {plan['target_id']}")
    if not npc.get("alive", True):
        return ruling("blocked", f"{npc['name']} is already dead.", notes, action="harm", precedent_key=key)
    if npc.get("down") and plan["result"] == "disabled":
        plan = {**plan, "result": "wounded"}  # Already down: another blow can only wound or kill.
    method = plan.get("method", "melee")
    weapon = plan.get("weapon_id")
    if weapon is not None and weapon not in available:
        return unresolved(notes, f"weapon is not at hand: {weapon}")
    result = plan["result"]
    if method == "poured" and weapon is None:  # Unnamed, but only one thing in hand holds water: that one.
        held = [o["id"] for o in available.values() if o["holder_id"] == "player" and o.get("water_l", 0) > 0]
        if len(held) == 1:
            weapon = held[0]
            notes.append(f"Poured from {weapon}, the only thing in hand holding water.")
    if method == "poured":  # A law: only what's really hot can scald; cold water only soaks.
        container = available.get(weapon) if weapon else None
        if container is None or container.get("water_l", 0) <= 0:
            return ruling("blocked", "There's nothing in your hands to pour.", notes, action="harm", precedent_key=key)
        if container.get("temperature", "cold") in ("cold", "warm") and result != "missed":
            reason = f"The water only soaks {npc['name']}."
    distance = cast.distance(state["player"], npc)
    picked_up = []
    if method == "thrown":
        thrown = available.get(weapon) if weapon else None
        if thrown is None or thrown["holder_id"] != "player":
            return ruling(
                "blocked", "You need to be holding something to throw it.", notes, action="harm", precedent_key=key
            )
        if "carry" not in thrown["capabilities"] or thrown["mass_kg"] > tuning.MAX_THROW_KG:
            return ruling(
                "blocked", f"The {thrown['name']} is too heavy to throw.", notes, action="harm", precedent_key=key
            )
        if distance > tuning.THROW_RANGE:
            return ruling(
                "blocked",
                f"{npc['name']} is too far away to throw at.",
                notes + [f"Blocked by code: target {distance:.1f} cells away (throw range {tuning.THROW_RANGE:.0f})."],
                action="harm",
                precedent_key=key,
            )
    else:
        if distance > tuning.REACH_CELLS:
            return ruling(
                "blocked",
                f"{npc['name']} is too far away to reach.",
                notes + [f"Blocked by code: target {distance:.1f} cells away (reach {tuning.REACH_CELLS})."],
                action="harm",
                precedent_key=key,
            )
        if weapon is not None and available[weapon]["holder_id"] != "player":
            if "carry" not in available[weapon]["capabilities"]:
                return ruling(
                    "blocked",
                    f"You can't wield the {available[weapon]['name']}.",
                    notes,
                    action="harm",
                    precedent_key=key,
                )
            picked_up = [weapon]  # Picked up on the way.
    witnesses = [
        n["id"]
        for n in state["npcs"]
        if n["id"] != npc["id"] and n.get("alive", True) and cast.distance(state["player"], n) <= tuning.WITNESS_RADIUS
    ]
    outcome = _blow(state, npc, plan, method, available.get(weapon) if weapon else None, result, notes, effort)
    if outcome["result"] == "deflected" and result not in ("missed", "deflected") and method != "poured":
        reason = f"The blow glances off {npc['name']}'s armour." if outcome.get("armoured") else reason
    if outcome["result"] == "killed" and result != "killed":  # The wounds add up (the bug players saw with Tomas).
        reason = reason.rstrip() + f" {npc['name']} does not survive this wound."
        notes.append("Wound was fatal: the injuries added up (health reached 0).")
    harm = {
        "target_id": npc["id"],
        "weapon_id": weapon,
        "method": method,
        "result": outcome["result"],
        "family": outcome["family"],
        "area": outcome["area"],
        "effective": outcome["effective"],
        "conditions": outcome["conditions"],
        "down": outcome["down"],
        "kill": outcome["kill"],
        "injury": plan["injury"].strip()[:200]
        if outcome["result"] not in ("missed", "deflected")
        else "soaked but unhurt"
        if method == "poured"
        else plan["injury"].strip()[:200],
        "witnesses": witnesses,
    }
    soaked = []
    landed = plan.get("outcome") == "landed" and plan["result"] != "missed"  # As the judge saw it, before the laws.
    if method == "poured" and landed:  # A law: liquid poured over someone leaves them wet (D-65).
        vessel = available[weapon]
        soaked = [
            {
                "kind": "condition",
                "target_id": npc["id"],
                "name": "soaked",
                "value": f"drenched with water from the {vessel['name']}",
                "minutes": tuning.SOAKED_MINUTES,
                "limits": [],
            }
        ]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="harm",
        harm=harm,
        precedent_key=key,
        take_ids=picked_up,
        property=_property(state, picked_up, "taken"),
        effects=soaked,
    )


FAMILY_OF_METHOD = {"melee": "blow", "thrown": "missile", "poured": "pour"}


def _blow(
    state: State, npc: Npc, plan: dict, method: str, weapon: dict | None, result: str, notes: list[str], effort: int = 0
) -> dict:
    """What a described attack does (D-49): the judge rules whether it lands, where, and (for a choke or anything
    else) how; code works out what that does to this person with gear.hit."""
    family = plan.get("family") or FAMILY_OF_METHOD.get(method, "blow")
    area = plan.get("target_area") or "torso"
    landed = plan.get("outcome", "landed" if result not in ("missed",) else "missed")
    base = {"family": family, "area": area, "effective": 0.0, "conditions": [], "down": False, "kill": False}
    if landed == "missed" or result == "missed":
        return {**base, "result": "missed"}
    if landed == "blocked":
        return {**base, "result": "deflected"}
    aware = cast.aware(state, npc)
    if family == "pour":
        profile = {}
    elif family == "missile" and weapon is not None:
        profile = gear.thrown(weapon)
    else:
        profile = gear.weapon(weapon)
    outcome = gear.hit(
        state,
        npc,
        profile,
        area=area,
        aware=aware,
        held_down=bool(npc.get("down")),
        family=family,
        liquid=weapon if family == "pour" else None,
        held_seconds=max(int(plan.get("held_seconds") or 0), effort if family == "choke" else 0),
        judged=result,
    )
    if family == "pour" and weapon and weapon.get("temperature", "cold") in ("cold", "warm"):
        notes.append("Law: cold or warm water can't wound.")
    if outcome["deflected"] or (outcome["effective"] < 1 and outcome["result"] != "killed"):
        notes.append(
            f"Law: {profile.get('name', 'the blow')} against what {npc['name']} wears: "
            f"{outcome['effective']} gets through."
        )
    word = outcome["result"]
    if word not in ("missed", "deflected"):
        probe = {k: npc.get(k) for k in ("id", "health", "alive", "down")}
        probe["conditions"] = []
        word = gear.apply(probe, outcome, 0)
    return {
        **base,
        "family": family,
        "result": word,
        "effective": outcome["effective"],
        "conditions": outcome["conditions"],
        "down": outcome["down"] or word in ("disabled", "knocked_out"),
        "kill": outcome["kill"] or word == "killed",
        "armoured": outcome["deflected"],
    }


def _fill(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("fill")
    if not plan:
        return unresolved(notes, "action 'fill' without a fill")
    container, source = available.get(plan["container_id"]), state["objects"].get(plan["source_id"])
    if container is None:
        return unresolved(notes, f"container is not within reach: {plan['container_id']}")
    if source is None or "water_source" not in source["capabilities"]:
        return unresolved(notes, f"not a water source: {plan['source_id']}")
    if "container" not in container.get("flags", []) or not container.get("capacity_l"):
        return ruling("blocked", f"The {container['name']} can't hold water.", notes, action="fill", precedent_key=key)
    if container.get("closed"):  # D-65: shut or sealed.
        return ruling("blocked", f"The {container['name']} is closed.", notes, action="fill", precedent_key=key)
    if cast.distance(state["player"], cast.nearest(source, state["player"])) > tuning.REACH_CELLS:
        return ruling("blocked", f"The {source['name']} is too far away.", notes, action="fill", precedent_key=key)
    room = round(container["capacity_l"] - container.get("water_l", 0.0), 3)
    if room <= 0:
        return ruling("blocked", f"The {container['name']} is already full.", notes, action="fill", precedent_key=key)
    if source["water_l"] <= 0:
        return ruling("blocked", f"The {source['name']} is empty.", notes, action="fill", precedent_key=key)
    requested = float(plan["litres"]) if float(plan["litres"]) > 0 else room
    litres = round(min(requested, room, source["water_l"]), 3)
    if litres < requested:
        notes.append(f"Filled {litres} L, not {requested} L: limited by space or the water available.")
    if container["holder_id"] == "player" and m2.inventory_mass(state) + litres > tuning.CARRY_LIMIT_KG:
        return ruling(
            "blocked", "That much water would be more than you can carry.", notes, action="fill", precedent_key=key
        )
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="fill",
        precedent_key=key,
        fill={"container_id": container["id"], "source_id": source["id"], "litres": litres},
        property=_property(state, [container["id"], source["id"]], "used"),
    )


def _demonstrate(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("demonstration")
    if not plan:
        return unresolved(notes, "action 'demonstrate' without a demonstration")
    ids = _dedupe([plan["object_id"]] + list(plan["used_ids"]))
    water = [i for i in ids[1:] if "water_source" in state["objects"].get(i, {}).get("capabilities", [])]
    missing = [i for i in ids if i not in available and i not in water]
    if missing:
        return unresolved(notes, f"can only show things that are at hand: {missing}")
    far = [
        state["objects"][i]["name"]
        for i in water
        if cast.distance(state["player"], state["objects"][i]) > tuning.REACH_CELLS
    ]
    if far:
        return ruling("blocked", f"The {far[0]} is too far away.", notes, action="demonstrate", precedent_key=key)
    shown = available[plan["object_id"]]
    living = {
        n["id"]
        for n in state["npcs"]
        if n.get("alive", True)
        and not n.get("down")
        and cast.distance(n, state["player"]) <= tuning.SIGHT_CELLS
        and paths.line_of_sight(state, cast.cell(n), cast.player_cell(state))
    }
    results = [
        {"text": " ".join(r["text"].split())[:120], "status": r["status"]}
        for r in plan["capabilities"][:4]
        if r["text"].strip() and r["status"] in ("observed", "failed")
    ]
    demonstration = {
        "object_id": shown["id"],
        "object_name": shown["name"],
        "used_ids": ids[1:],
        "audience_ids": [i for i in _dedupe(plan["audience_ids"]) if i in living],
        "observed": " ".join(plan["observed"].split())[:300] or f"The stranger showed a {shown['name']}.",
        "works": bool(plan["works"]),
        "results": results,
        "wonder": plan.get("wonder", "ordinary") if plan["works"] else "ordinary",
    }
    not_ours = [i for i in ids if i in water or available[i]["holder_id"] != "player"]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="demonstrate",
        demonstration=demonstration,
        precedent_key=key,
        property=_property(state, not_ours, "used"),
    )


def _give(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("give")
    if not plan:
        return unresolved(notes, "action 'give' without a give")
    npc = next((n for n in state["npcs"] if n["id"] == plan["recipient_id"]), None)
    if npc is None:
        return unresolved(notes, f"give recipient is not a person: {plan['recipient_id']}")
    if not npc.get("alive", True):
        return ruling("blocked", f"{npc['name']} is dead.", notes, action="give", precedent_key=key)
    ids = _dedupe(plan["item_ids"])
    loose = [i for i in ids if state["objects"].get(i, {}).get("holder_id") != "player"]
    if not ids or loose:
        known = state["objects"].get(loose[0]) if loose else None
        what = f"the {known['name']}" if known else "that" if loose else "anything"
        return ruling("blocked", f"You aren't carrying {what} to give.", notes, action="give", precedent_key=key)
    if cast.distance(state["player"], npc) > tuning.REACH_CELLS:
        return ruling(
            "blocked", f"{npc['name']} is too far away to hand anything to.", notes, action="give", precedent_key=key
        )
    others = [i for i in ids if state["objects"][i]["owner_id"] not in (None, "player", npc["id"])]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="give",
        precedent_key=key,
        give={
            "item_ids": ids,
            "recipient_id": npc["id"],
            "recipient_name": npc["name"],
            "names": [_given_name(state["objects"][i]) for i in ids],
        },
        property=_property(state, others, "given away"),
    )


def _given_name(obj: dict) -> str:
    """A thing as the person handed it sees it: a container says how much water is in it, and whether it's full."""
    water = obj.get("water_l") or 0.0
    if not water:
        return obj["name"]
    full = obj.get("capacity_l") and water >= obj["capacity_l"]
    return obj["name"] + (f", full ({water:g} L of water)" if full else f" with {water:g} L of water in it")


def _aids(state: State, plan: dict, available: dict, skip: tuple) -> tuple[list[str], list[str], list[str]]:
    """The aids a lift names: things at hand, and people close by (to the stranger or the thing) and willing to help
    (D-59). Returns (things, helpers, anything named that is neither)."""
    things, helpers, missing = [], [], []
    moved = state["objects"].get(skip[0]) or {}
    at = (moved["x"], moved["y"]) if "x" in moved else None
    for aid in _dedupe(plan["aid_ids"]):
        if aid in skip:
            continue
        person = cast.find(state["npcs"], aid)
        if aid in available:
            things.append(aid)
        elif person is not None and reputation.will_help(state, person, at):
            helpers.append(aid)
        else:
            missing.append(aid)
    return things, helpers, missing


def _helper_names(state: State, helpers: list[str]) -> list[str]:
    return [cast.find(state["npcs"], i)["name"] for i in helpers]


def _install(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("install")
    if not plan:
        return unresolved(notes, "action 'install' without an install")
    obj, into = available.get(plan["object_id"]), available.get(plan["into_id"])
    if obj is None or into is None:
        return unresolved(
            notes, f"install needs the object and the fixture at hand: {plan['object_id']}, {plan['into_id']}"
        )
    if into.get("feature") != "fixture":
        return ruling(
            "blocked",
            f"The {obj['name']} can't be fitted into the {into['name']}.",
            notes,
            action="install",
            precedent_key=key,
        )
    if obj.get("installed_in"):
        return ruling("blocked", f"The {obj['name']} is already in place.", notes, action="install", precedent_key=key)
    held = next((o for o in state["objects"].values() if o.get("installed_in") == into["id"]), None)
    if held is not None:  # One thing at a time in a fixture: the old one has to come out first.
        return ruling(
            "blocked",
            f"The {into['name']} already hold the {held['name']}.",
            notes,
            action="install",
            precedent_key=key,
        )
    aids, helpers, missing = _aids(state, plan, available, (obj["id"], into["id"]))
    if missing:
        return unresolved(notes, f"aids that are not at hand (or people not willing to help): {missing}")
    if obj["mass_kg"] > tuning.CARRY_LIMIT_KG and not (aids or helpers):
        return ruling(
            "blocked",
            f"The {obj['name']} is far too heavy to lift into place by hand.",
            notes + ["Blocked by code: heavier than one person can lift, and no aids."],
            action="install",
            precedent_key=key,
        )
    install = {
        "object_id": obj["id"],
        "object_name": obj["name"],
        "into_id": into["id"],
        "into_name": into["name"],
        "aid_ids": aids,
        "aid_names": [available[i]["name"] for i in aids],
        **({"helper_ids": helpers, "helper_names": _helper_names(state, helpers)} if helpers else {}),
    }
    # Putting something where it belongs isn't taking it; borrowing someone's tools to do it is.
    not_ours = [i for i in aids if available[i]["holder_id"] != "player"]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="install",
        install=install,
        precedent_key=key,
        property=_property(state, not_ours, "used"),
    )


def _lift_out(state, judged, available, notes, reason, effort, key) -> dict:
    """The inverse of install: work something out of its fixture and down to the ground (D-42)."""
    plan = judged.get("lift_out")
    if not plan:
        return unresolved(notes, "action 'lift_out' without a lift_out")
    obj = available.get(plan["object_id"])
    if obj is None:
        return unresolved(notes, f"lift_out needs the object at hand: {plan['object_id']}")
    into = state["objects"].get(obj.get("installed_in") or "")
    if into is None:
        return ruling(
            "blocked", f"The {obj['name']} isn't fitted into anything.", notes, action="lift_out", precedent_key=key
        )
    aids, helpers, missing = _aids(state, plan, available, (obj["id"], into["id"]))
    if missing:
        return unresolved(notes, f"aids that are not at hand (or people not willing to help): {missing}")
    if obj["mass_kg"] > tuning.CARRY_LIMIT_KG and not (aids or helpers):
        return ruling(
            "blocked",
            f"The {obj['name']} is far too heavy to lift out by hand.",
            notes + ["Blocked by code: heavier than one person can lift, and no aids."],
            action="lift_out",
            precedent_key=key,
        )
    lifted = {
        "object_id": obj["id"],
        "object_name": obj["name"],
        "from_id": into["id"],
        "from_name": into["name"],
        "aid_ids": aids,
        "aid_names": [available[i]["name"] for i in aids],
        **({"helper_ids": helpers, "helper_names": _helper_names(state, helpers)} if helpers else {}),
    }
    not_ours = [i for i in aids if available[i]["holder_id"] != "player"]
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="lift_out",
        lift_out=lifted,
        precedent_key=key,
        property=_property(state, not_ours, "used"),
    )


def _offer_trade(state, judged, available, notes, reason, effort, key) -> dict:
    plan = judged.get("offer_trade")
    if not plan:
        return unresolved(notes, "action 'offer_trade' without an offer_trade")
    npc = next((n for n in state["npcs"] if n["id"] == plan["recipient_id"]), None)
    if npc is None:
        return unresolved(notes, f"trade partner is not a person: {plan['recipient_id']}")
    if not npc.get("alive", True):
        return ruling("blocked", f"{npc['name']} is dead.", notes, action="offer_trade", precedent_key=key)
    give, want = _dedupe(plan["give_ids"]), _dedupe(plan["want_ids"])
    mine = [
        i
        for i in give
        if (o := state["objects"].get(i)) and o["holder_id"] == "player" and o["owner_id"] in (None, "player")
    ]
    if not give or len(mine) != len(give):
        return ruling(
            "blocked",
            "You can only trade things that are yours and in your hands.",
            notes,
            action="offer_trade",
            precedent_key=key,
        )
    theirs = [
        i
        for i in want
        if (o := state["objects"].get(i))
        and o["owner_id"] == npc["id"]
        and o["holder_id"] in (None, npc["id"])
        and "carry" in o["capabilities"]
    ]
    if not want or len(theirs) != len(want):
        return unresolved(notes, f"can only ask for {npc['name']}'s own portable things: {want}")
    if cast.distance(state["player"], npc) > 5:
        return ruling(
            "blocked", f"{npc['name']} is too far away to bargain with.", notes, action="offer_trade", precedent_key=key
        )
    offer = {
        "recipient_id": npc["id"],
        "recipient_name": npc["name"],
        "give_ids": give,
        "want_ids": want,
        "give_names": [state["objects"][i]["name"] for i in give],
        "want_names": [state["objects"][i]["name"] for i in want],
    }
    return ruling("success", reason, notes, effort, action="offer_trade", offer_trade=offer, precedent_key=key)


def _gear_proposal(judged: dict | None) -> dict | None:
    """The judge's gear field in gear.py's shape ({kind, class, covers, quality})."""
    if not judged:
        return None
    return {
        "kind": judged.get("kind"),
        "class": judged.get("gear_class"),
        "covers": judged.get("covers") or [],
        "quality": judged.get("quality", "fair"),
    }


PROTECTED_ATTRIBUTES = {
    "owner_id",
    "holder_id",
    "health",
    "alive",
    "gate_open",
    "admitted",
    "mind",
    "trust",
    "permission",
    "mass_kg",
    "capacity_l",
    "rated_load_kg",
    "temperature",
    "burning",
    "water_l",
    "flags",
    "condition",
}


def _checked_attributes(spec, resources):
    attributes = copy.deepcopy(spec.get("attributes", []))
    for attribute in attributes:
        if (
            not attribute["name"].strip()
            or attribute["name"].strip().lower() in PROTECTED_ATTRIBUTES
            or len(attribute["name"]) > 80
            or len(attribute["value"]) > 400
            or not attribute.get("basis_ids")
            or any(i not in resources for i in attribute["basis_ids"])
        ):
            return None
        if attribute["status"] == "observed":
            attribute["status"] = "expected"
    return attributes


def _physical(state, judged, available, notes, reason, effort, key):
    """Changes to things already in the world, made only of effects (D-62); their laws are effects.py's, checked
    with every other step's (_with_effects)."""
    if not judged.get("effects"):
        return unresolved(notes, "physical work needs at least one effect")
    refs = set(judged.get("resource_ids", []))
    if any(i not in available for i in refs):
        return unresolved(notes, "physical work needs actual accessible resources")
    for helper_id in judged.get("helper_ids", []):
        helper = cast.find(state["npcs"], helper_id)
        if helper is None or not reputation.will_help(state, helper):
            return unresolved(notes, "the proposed helper has not committed to this work or is unavailable")
    used = sorted(refs | {e["target_id"] for e in judged["effects"] if e.get("target_id") in available})
    return ruling(
        "success",
        reason,
        notes,
        effort,
        action="physical",
        tool_ids=used,
        property=_property(state, used, "used"),
        precedent_key=key,
    )
