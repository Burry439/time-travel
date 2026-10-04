"""A ruled attempt becomes the world: each step validated against the world as it is by then, what it makes,
changes, moves or hurts worked out as changes, applied in order, and stopped at the first step that
doesn't succeed (GDD 6.2). Models propose; this is where what they proposed happens."""

from __future__ import annotations

import copy
import re

import actors
import cast
import clock
import content
import crafting
import gear
import heat
import judge_view
import m2
import paths
import perception
import precedents
import reputation
import store
import tuning
from shapes import State, Thing

CONTENT = content.MATERIALS


MAX_STEPS = 4


OPERATION_CAPABILITIES = {"tieable": "tie", "container": "fill"}


def gate_after(state: State, fixture_id: str, barred: bool) -> dict | None:
    """The gate stands open while nothing bars it (or the stranger has been let in); None if unaffected."""
    if fixture_id != m2.GATE_FIXTURE:
        return None
    return {"open": bool(state.get("admitted")) or not barred, **({} if barred else {"unbarred_by": "player"})}


def _known_after(obj: Thing, results: list[dict], event_id: int) -> list[dict]:
    """The object's capabilities with what a demonstration showed: matching ones updated, new ones added."""
    known = [dict(c) for c in obj.get("known_capabilities", [])]
    for result in results:
        match = next((c for c in known if c["text"].casefold() == result["text"].casefold()), None)
        if match is None:
            if len(known) >= 6:
                continue
            match = {"text": result["text"]}
            known.append(match)
        match.update(status=result["status"], event_id=event_id)
    return known


def placeholder_category(materials: list[str]) -> str:
    categories = CONTENT["placeholder_categories"]
    return next((categories[m] for m in materials if m in categories), "bundle")


def _picture_ids(spec: dict, sprite: str) -> dict:
    """A weapon or shield is also drawn in the hand, armour and clothes on the body (D-49)."""
    kind = (spec.get("gear") or {}).get("kind")
    if kind in ("weapon", "shield") and (spec.get("gear") or {}).get("class") not in ("improvised", None):
        return {"held_asset_id": f"{sprite}_held"}
    if kind in ("armour", "clothing"):
        return {"worn_asset_id": f"{sprite}_worn"}
    return {}


def _object(
    new_id: str,
    run_id: str,
    spec: dict,
    x: int,
    y: int,
    owner,
    holder,
    text: str,
    event_id: int,
    components: list[str],
    tools: list[str],
    asset_id: str | None = None,
) -> dict:
    portable = spec["mass_kg"] <= tuning.CARRY_LIMIT_KG
    caps = ["carry"] + [op for flag, op in OPERATION_CAPABILITIES.items() if flag in spec["flags"]] if portable else []
    return {
        "id": new_id,
        "name": spec["name"],
        "description": spec["description"],
        "x": x,
        "y": y,
        "mass_kg": spec["mass_kg"],
        "owner_id": owner,
        "holder_id": holder if portable else None,
        "capabilities": caps,
        "bound_to": [],
        "water_l": 0.0,
        "capacity_l": spec.get("capacity_l") or 0.0,
        "condition": "usable",
        "materials": spec["materials"],
        "flags": spec["flags"],
        "length_m": spec.get("length_m"),
        "rated_load_kg": spec.get("rated_load_kg"),
        "known_capabilities": spec["known_capabilities"],
        "attributes": copy.deepcopy(spec.get("attributes", [])),
        "revision": 0,
        "components": components,
        "tools_used": tools,
        **({"gear": spec["gear"]} if spec.get("gear") else {}),
        "created_by": "player",
        "created_event_id": event_id,
        "created_text": text,
        "sprite_asset_id": asset_id or f"spr_{run_id[:8]}_{new_id}",
        **_picture_ids(spec, asset_id or f"spr_{run_id[:8]}_{new_id}"),
        "placeholder": placeholder_category(spec["materials"]),
    }


def _step_deltas(
    state: State, run_id: str, text: str, verdict: dict, event_id: int, number: int, actor_id: str = "player"
) -> dict:
    """World changes for one validated step; ids stay unique across the steps of one attempt."""
    walk = verdict.get("walk") or []
    px, py = walk[-1] if walk else (state["player"]["x"], state["player"]["y"])
    step = {
        "run_id": run_id,
        "text": text,
        "event_id": event_id,
        "suffix": ("" if number == 1 else f"_{number}") + (f"_{actor_id}" if actor_id != "player" else ""),
        "at": (px, py),
    }
    work = CHANGES.get(verdict["action"])
    parts = work(state, verdict, step) if work else {}
    if verdict.get("hurt_self"):  # What it did to the stranger's own body (D-59).
        body = {k: verdict["hurt_self"][k] for k in ("conditions", "health")}
        parts.setdefault("water", []).append({"id": "__player__", **body})
    deltas = {
        "effects": verdict.get("effects", []),
        "consumed_ids": parts.get("consumed_ids", []),
        "new_objects": parts.get("new_objects", []),
        "taken_ids": parts.get("taken_ids", []),
        "transformed": parts.get("transformed"),
        "npc_updates": parts.get("npc_updates", []),
        "moved": parts.get("moved", []),
        "walk": walk,
        "player_to": [px, py] if walk else None,
    }
    deltas.update(
        {
            key: parts[key]
            for key in ("water", "capabilities", "given", "spilled_l", "installed", "trade", "lifted_out")
            if parts.get(key)
        }
    )
    if parts.get("gate") is not None:
        deltas["gate"] = parts["gate"]
    return deltas


def _made(state: State, verdict: dict, step: dict) -> dict:
    """Something new, from what went into it: in hand if it can be carried with the rest, else at their feet."""
    spec = verdict["new_spec"]
    consumed = verdict["consumed_ids"]
    carried_consumed = sum(
        state["objects"][i]["mass_kg"] + state["objects"][i]["water_l"]
        for i in consumed
        if state["objects"][i]["holder_id"] == "player"
    )
    fits = m2.inventory_mass(state) - carried_consumed + spec["mass_kg"] <= tuning.CARRY_LIMIT_KG
    if not fits:
        verdict["notes"].append("Too heavy to carry with the current load; left at the player's feet.")
    made = _object(
        f"made_{step['event_id']}{step['suffix']}",
        step["run_id"],
        spec,
        *step["at"],
        "player",
        "player" if fits else None,
        step["text"],
        step["event_id"],
        consumed,
        verdict["tool_ids"],
    )
    if spec.get("burning"):  # A fire: it stays where it was lit and burns down with its fuel.
        span = max(tuning.FIRE_MS_RANGE[0], min(tuning.FIRE_MS_RANGE[1], int(spec["mass_kg"] * tuning.FIRE_MS_PER_KG)))
        hearth = next(  # Lit in something fixed (Ulf's fire pit, a hearth), or beside one: it burns there (D-59).
            (o for i in verdict["tool_ids"] if "carry" not in (o := state["objects"][i]).get("capabilities", [])),
            None,
        ) or min(
            (
                o
                for o in state["objects"].values()
                if o.get("feature") == "hearth" and cast.distance(step["at"], o) <= tuning.REACH_CELLS
            ),
            key=lambda o: cast.distance(step["at"], o),
            default=None,
        )
        if hearth is not None:
            made.update(x=hearth["x"], y=hearth["y"])
        made.update(
            burning=True,
            feature="fire",
            capabilities=[],
            holder_id=None,
            burns_until=state["sim_time_ms"] + verdict["effort_seconds"] * 1000 + span,
        )
    # Water in anything built in stays in the new thing if it holds water; otherwise it spills.
    held = round(sum(state["objects"][i].get("water_l", 0.0) for i in consumed), 3)
    kept = min(held, spec.get("capacity_l") or 0.0) if "container" in spec["flags"] else 0.0
    made["water_l"] = kept
    drawn = [  # Water that went into the thing made: out of its container (D-63).
        {"id": d["id"], "water_l": round(max(0.0, state["objects"][d["id"]].get("water_l", 0.0) - d["litres"]), 3)}
        for d in verdict.get("water_draws", [])
        if state["objects"][d["id"]].get("water_l", 0.0) > 0
    ]
    return {
        "consumed_ids": consumed,
        "new_objects": [made],
        "spilled_l": round(held - kept, 3),
        **({"water": drawn} if drawn else {}),
    }


def _pieces(verdict: dict, step: dict, prefix: str, piece: dict, numbers: range, where, owner, keep, source_id):
    """Identical pieces, numbered as given and sharing one painting: where() gives each one's cell, keep(piece)
    whether it stays in hand."""
    made, asset_id = [], None
    for index in numbers:
        obj = _object(
            f"{prefix}_{step['event_id']}{step['suffix']}_{index}",
            step["run_id"],
            piece,
            *where(),
            owner,
            "player" if keep(piece) else None,
            step["text"],
            step["event_id"],
            [source_id],
            verdict["tool_ids"],
            asset_id,
        )
        asset_id = obj["sprite_asset_id"]
        made.append(obj)
    return made


def _gathered(state: State, verdict: dict, step: dict) -> dict:
    """New small things in hand; the source stays as it was (a small one is that much smaller)."""
    plan = verdict["gather"]
    source = state["objects"][plan["source_id"]]
    owner = source["owner_id"] if source["owner_id"] not in (None, "player") else "player"
    piece, count = plan["piece"], plan["piece"]["count"]
    numbers = range(1, count + 1)
    made = _pieces(verdict, step, "gathered", piece, numbers, lambda: step["at"], owner, lambda _: True, source["id"])
    parts = {"new_objects": made}
    if "carry" in source["capabilities"]:  # A tree doesn't notice.
        left = max(0.01, round(source["mass_kg"] - piece["mass_kg"] * count, 3))
        parts["water"] = [{"id": source["id"], "mass_kg": left}]
    return parts


def _treated(state: State, verdict: dict, step: dict) -> dict:
    treated = verdict["treat"]
    parts: dict = {"water": [], "npc_updates": [], "moved": []}
    if treated["patient_id"] == "player":
        parts["water"].append({"id": "__player__", "conditions": treated["conditions"]})
    else:
        parts["npc_updates"].append({"id": treated["patient_id"], "conditions": treated["conditions"]})
    if treated["consumed"]:
        parts["moved"].append({"id": treated["consumed"], "used_up": True})
    return parts


def _transformed(state: State, verdict: dict, step: dict) -> dict:
    """Cut, broken, felled: the pieces lie around it (or stay in hand while they can be carried)."""
    plan = verdict["transform"]
    target = state["objects"][plan["target_id"]]
    cleared = paths.cleared_obstacles(state) | ({target["geometry_name"]} if target.get("geometry_name") else set())
    in_hand = target["holder_id"] == "player"
    load = [m2.inventory_mass(state) - (target["mass_kg"] if in_hand else 0)]
    total = sum(p["count"] for p in plan["pieces"])
    px, py = step["at"]
    cells = iter(
        paths.open_cells_near(state, px if in_hand else target["x"], py if in_hand else target["y"], cleared, total)
    )
    owner = "player" if target["owner_id"] == "player" else target["owner_id"]

    def keep(piece: dict) -> bool:
        kept = in_hand and load[0] + piece["mass_kg"] <= tuning.CARRY_LIMIT_KG
        load[0] += piece["mass_kg"] if kept else 0
        return kept

    made = []
    for piece in plan["pieces"]:  # Numbered across every kind of piece.
        numbers = range(len(made) + 1, len(made) + piece["count"] + 1)
        made += _pieces(verdict, step, "piece", piece, numbers, lambda: next(cells), owner, keep, plan["target_id"])
    transformed = {"id": plan["target_id"], "result_state": plan["result_state"], "into": [o["id"] for o in made]}
    return {"new_objects": made, "transformed": transformed}


def _harmed(state: State, verdict: dict, step: dict) -> dict:
    """What gear.hit worked out (D-49), carried out on the person; a thrown weapon lands by them, a poured one is
    emptied over them."""
    harm = verdict["harm"]
    npc = next(n for n in state["npcs"] if n["id"] == harm["target_id"])
    body = {k: copy.deepcopy(npc.get(k)) for k in ("id", "health", "alive", "down", "conditions")}
    body["health"] = body["health"] if body["health"] is not None else 100
    body["alive"] = body["alive"] if body["alive"] is not None else True
    body["conditions"] = body["conditions"] or []
    if harm["result"] not in ("missed", "deflected"):
        gear.apply(body, harm, state["sim_time_ms"])
    health, down = body["health"], bool(body.get("down"))
    if harm["result"] == "killed":
        health = 0
    injuries = npc.get("injuries", []) + ([harm["injury"]] if harm["result"] not in ("missed", "deflected") else [])
    update = {
        "id": npc["id"],
        "alive": health > 0,
        "health": health,
        "injuries": injuries,
        "conditions": body["conditions"],
        **({"down": True} if down and health > 0 else {}),
    }
    if harm["result"] == "killed" and not verdict["reason"].rstrip().endswith("."):
        verdict["reason"] = verdict["reason"].rstrip() + "."
    parts = {"npc_updates": [update], "taken_ids": verdict["take_ids"], "moved": []}  # A weapon picked up on the way.
    if harm["method"] == "thrown" and harm["weapon_id"]:
        x, y = paths.open_cells_near(state, npc["x"], npc["y"], paths.cleared_obstacles(state), 1)[0]
        parts["moved"].append({"id": harm["weapon_id"], "x": x, "y": y})
    if harm["method"] == "poured" and harm["weapon_id"]:  # Emptied over them.
        parts["spilled_l"] = state["objects"][harm["weapon_id"]].get("water_l", 0.0)
        parts["water"] = [{"id": harm["weapon_id"], "water_l": 0.0, "temperature": "cold", "heated_at": None}]
    return parts


def _filled(state: State, verdict: dict, step: dict) -> dict:
    fill = verdict["fill"]
    container, source = state["objects"][fill["container_id"]], state["objects"][fill["source_id"]]
    return {
        "water": [
            {"id": container["id"], "water_l": round(container.get("water_l", 0.0) + fill["litres"], 3)},
            {"id": source["id"], "water_l": round(source["water_l"] - fill["litres"], 3)},
        ]
    }


def _changed(state: State, verdict: dict, step: dict) -> dict:
    change = verdict["change"]
    return {"water": [{"id": change["id"], **change["fields"]}] + change["pour"], "spilled_l": change["spilled_l"]}


def _shown(state: State, verdict: dict, step: dict) -> dict:
    shown = verdict["demonstration"]
    known = _known_after(state["objects"][shown["object_id"]], shown["results"], step["event_id"])
    return {"capabilities": {"id": shown["object_id"], "known_capabilities": known}}


def _installed(state: State, verdict: dict, step: dict) -> dict:
    plan = verdict["install"]
    into = state["objects"][plan["into_id"]]
    return {
        "installed": {"id": plan["object_id"], "into": plan["into_id"], "x": into["x"], "y": into["y"]},
        "gate": gate_after(state, plan["into_id"], barred=True),
    }


def _lifted(state: State, verdict: dict, step: dict) -> dict:
    plan = verdict["lift_out"]
    fixture = state["objects"][plan["from_id"]]
    x, y = paths.open_cells_near(state, fixture["x"], fixture["y"] + 2, paths.cleared_obstacles(state), 1)[0]
    return {
        "lifted_out": {"id": plan["object_id"], "x": x, "y": y},
        "gate": gate_after(state, plan["from_id"], barred=False),
    }


def _trade_offered(state: State, verdict: dict, step: dict) -> dict:
    trade = {
        **verdict["offer_trade"],
        "id": f"trade_{step['event_id']}{step['suffix']}",
        "status": "offered",
        "offered_event": step["event_id"],
    }
    return {"trade": trade}


def _given(state: State, verdict: dict, step: dict) -> dict:
    """A gift of your own (or unowned) thing makes it theirs; someone else's thing stays theirs."""
    give = verdict["give"]
    owners = {
        i: give["recipient_id"]
        if state["objects"][i]["owner_id"] in (None, "player")
        else state["objects"][i]["owner_id"]
        for i in give["item_ids"]
    }
    return {"given": {"ids": give["item_ids"], "to": give["recipient_id"], "owners": owners}}


# What each kind of step changes in the world (a step with nothing to change, like waiting, has no entry).
CHANGES = {
    "make": _made,
    "take": lambda state, verdict, step: {"taken_ids": verdict["take_ids"]},
    "gather": _gathered,
    "treat": _treated,
    "equip": lambda state, verdict, step: {"water": [{"id": "__player__", "equipped": verdict["equip"]["equipped"]}]},
    "drop": lambda state, verdict, step: {
        "moved": [{"id": i, "x": step["at"][0], "y": step["at"][1]} for i in verdict["drop_ids"]]
    },
    "transform": _transformed,
    "harm": _harmed,
    "fill": _filled,
    "change": _changed,
    "demonstrate": _shown,
    "install": _installed,
    "lift_out": _lifted,
    "offer_trade": _trade_offered,
    "give": _given,
}


def apply_step(state: State, deltas: dict, actor_id: str = "player") -> None:
    actor = state["player"] if actor_id == "player" else cast.find(state["npcs"], actor_id)
    for effect in deltas.get("effects", []):
        obj = state["objects"][effect["target_id"]]
        if effect["kind"] == "attribute":
            attributes = obj.setdefault("attributes", [])
            prior = next((a for a in attributes if a["name"] == effect["attribute"]["name"]), None)
            if prior != effect["attribute"]:
                attributes[:] = [a for a in attributes if a["name"] != effect["attribute"]["name"]]
                attributes.append(copy.deepcopy(effect["attribute"]))
                obj["revision"] = obj.get("revision", 0) + 1
                sprite = f"spr_{state['run_id'][:8]}_{obj['id']}_r{obj['revision']}"
                obj.update(sprite_asset_id=sprite, picture_event_id=state["event_seq"] + 1)
                obj.update(_picture_ids(obj, sprite))
        else:
            other = state["objects"][effect["other_id"]]
            for first, second in ((obj, other), (other, obj)):
                links = first.setdefault("bound_to", [])
                changed = False
                if effect["kind"] == "connect" and second["id"] not in links:
                    links.append(second["id"])
                    changed = True
                elif effect["kind"] == "disconnect" and second["id"] in links:
                    links.remove(second["id"])
                    changed = True
                if changed:
                    first["revision"] = first.get("revision", 0) + 1
    if deltas.get("player_to"):
        actor.update(x=deltas["player_to"][0], y=deltas["player_to"][1])
    for landed in deltas.get("moved", []):
        if landed.get("used_up"):  # A bandage or poultice, used (D-49).
            state["objects"][landed["id"]].update(holder_id="used", condition="used up")
            continue
        state["objects"][landed["id"]].update(x=landed["x"], y=landed["y"], holder_id=None)
    new_objects = deltas.get("new_objects") or []
    if new_objects:
        for item_id in deltas["consumed_ids"]:
            # Its water went into the new thing (or spilled): see _step_deltas.
            state["objects"][item_id].update(holder_id=f"in:{new_objects[0]['id']}", water_l=0.0)
        for obj in new_objects:
            state["objects"][obj["id"]] = obj
            heat.rename(obj)
    for item_id in deltas.get("taken_ids", []):
        state["objects"][item_id]["holder_id"] = actor_id
    for change in deltas.get("water", []):  # Water moved, heated, poured; any change of state in place.
        if change["id"] == "__player__":  # The stranger's own body and kit (D-49).
            actor.update(copy.deepcopy({k: v for k, v in change.items() if k != "id"}))
            continue
        state["objects"][change["id"]].update({k: v for k, v in change.items() if k != "id"})
        if not state["objects"][change["id"]].get("water_l"):
            state["objects"][change["id"]].update(
                temperature=state["objects"][change["id"]].get("temperature", "cold")
                if not state["objects"][change["id"]].get("capacity_l")
                else "cold"
            )
        heat.rename(state["objects"][change["id"]])
    if deltas.get("spilled_l"):
        state["water_spilled_l"] = round(state.get("water_spilled_l", 0.0) + deltas["spilled_l"], 3)
    if deltas.get("capabilities"):
        state["objects"][deltas["capabilities"]["id"]]["known_capabilities"] = deltas["capabilities"][
            "known_capabilities"
        ]
    if deltas.get("lifted_out"):
        down = deltas["lifted_out"]
        state["objects"][down["id"]].update(
            installed_in=None, x=down["x"], y=down["y"], holder_id=None, condition="usable"
        )
    if deltas.get("gate"):  # The gate follows its bar (D-42).
        state["gate_open"] = deltas["gate"]["open"]
        if deltas["gate"].get("unbarred_by"):
            state["gate_unbarred_by"] = deltas["gate"]["unbarred_by"]
    if deltas.get("installed"):
        placed = deltas["installed"]
        state["objects"][placed["id"]].update(
            installed_in=placed["into"], x=placed["x"], y=placed["y"], holder_id=None, condition="installed"
        )
    if deltas.get("trade"):
        state.setdefault("trades", {})[deltas["trade"]["id"]] = dict(deltas["trade"])
    given = deltas.get("given")
    for item_id in (given or {}).get("ids", []):
        state["objects"][item_id].update(holder_id=given["to"], owner_id=given["owners"][item_id], given_by=actor_id)
        if given["owners"][item_id] == given["to"]:
            state["objects"][item_id].pop("lent_to", None)  # Back in its owner's hands: the loan is over.
    transformed = deltas.get("transformed")
    if transformed:
        target = state["objects"][transformed["id"]]
        target.update(
            condition=transformed["result_state"],
            holder_id=f"into:{transformed['into'][0]}",
            became=transformed["into"],
        )
    for update in deltas.get("npc_updates", []):
        npc = next(n for n in state["npcs"] if n["id"] == update["id"])
        if "alive" not in update:  # Only their conditions changed (someone treated them, D-49).
            npc["conditions"] = copy.deepcopy(update.get("conditions", npc.get("conditions", [])))
            continue
        npc.update(alive=update["alive"], health=update["health"])
        if "injuries" in update:
            npc["injuries"] = list(update["injuries"])
        if "conditions" in update:
            npc["conditions"] = copy.deepcopy(update["conditions"])
        if not update["alive"] and npc.get("controller"):
            npc["controller"].update(activity="dead", path=[], source="dead")
        elif update.get("down") and not npc.get("down"):
            npc["down"] = True
            if npc.get("mind"):
                npc["mind"]["job"] = None
            if npc.get("controller"):
                npc["controller"].update(activity="down", path=[], source="down")


_REFERENCE = re.compile(r"^made_by_step_(\d+)$")


def _resolve_references(step: dict, made_by_step: dict[int, str]) -> dict:
    """Point 'made_by_step_N' at the object that step actually made, wherever a later step names it (the thing
    to show, light, fill, give, fit or pour into as well as a weapon or ingredient)."""

    def swap(value):
        if isinstance(value, dict):
            return {k: swap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [swap(v) for v in value]
        match = _REFERENCE.match(value) if isinstance(value, str) else None
        return made_by_step.get(int(match.group(1)), value) if match else value

    return swap(copy.deepcopy(step))


def humanize(text: str, state: State, made_by_step: dict[int, str]) -> str:
    """Replace any id that leaked into player-facing text with the thing's name."""
    names = {oid: ("the ", o["name"]) for oid, o in state["objects"].items()}
    names.update({f"made_by_step_{n}": ("the ", state["objects"][oid]["name"]) for n, oid in made_by_step.items()})
    names.update({n["id"]: ("", n["name"]) for n in state["npcs"]})
    pattern = re.compile(
        r"\b(the |your |a |an )?(" + "|".join(re.escape(key) for key in sorted(names, key=len, reverse=True)) + r")\b"
    )

    def swap(match):
        article = match.group(1)
        default, name = names[match.group(2)]
        return ((article or default) if default else "") + name

    return pattern.sub(swap, text)


def resolve_attempt(
    state: State,
    run_id: str,
    text: str,
    judged: dict | None,
    service_error: str | None,
    trace_id: str,
    now_ms: int,
    actor_id: str = "player",
) -> tuple[dict, dict, dict]:
    """Validate and apply the judge's steps in order on a draft world; stop at the first that fails.

    Returns (event payload, summary verdict for the trace, draft state after the committed steps).
    """
    event_id = state["event_seq"] + 1
    draft = copy.deepcopy(state)
    actor = draft["player"] if actor_id == "player" else cast.find(draft["npcs"], actor_id)
    verdicts, deltas, made_by_step = [], [], {}
    if judged is None:
        verdicts.append(crafting.validate(draft, None, service_error))
    elif judged.get("clarifying_question"):
        verdicts.append(crafting.ruling("needs_clarification", judged["clarifying_question"], []))
    elif not judged.get("steps"):
        verdicts.append(crafting.unresolved([], "the judge returned no steps"))
    else:
        for number, step in enumerate(judged["steps"][:MAX_STEPS], 1):
            proposal = _resolve_references(step, made_by_step)
            proposal["precedent_key"] = judged.get("precedent_key")
            actor_view = actors.view(draft, actor_id)
            if (
                proposal.get("action") == "take"
                and proposal.get("outcome") == "success"
                and proposal.get("take_ids")
                and all(actor_view["objects"].get(i, {}).get("holder_id") == "player" for i in proposal["take_ids"])
                and not proposal.get("effects")
                and not proposal.get("hurts_you")
                and len(judged["steps"]) > 1
            ):
                # A satisfied prerequisite is not a new deed, and cannot stop the actual work.
                continue
            verdict = crafting.validate(actor_view, proposal)
            if verdict["category"] != "success":
                if verdict["category"] == "failed":
                    _advance(draft, verdict["effort_seconds"] * 1000)
                _precedent(draft, draft, proposal, verdict, text)
                verdicts.append(verdict)
                break
            start = draft["sim_time_ms"]
            interrupted = False
            # Walking and work happen before the effect, in bounded stretches of world time.
            walk = verdict.get("walk", [])
            walk_ms = min(verdict["effort_seconds"] * 1000, len(walk) * tuning.WALK_STEP_MS)
            for cell in walk:
                actor = draft["player"] if actor_id == "player" else cast.find(draft["npcs"], actor_id)
                actor.update(x=cell[0], y=cell[1])
                _advance(draft, tuning.WALK_STEP_MS)
                if _interrupted(draft, actor_id):
                    interrupted = True
                    break
            remaining = max(0, verdict["effort_seconds"] * 1000 - walk_ms)
            while remaining and not interrupted:
                span = min(remaining, 100 if draft.get("fight") else 10000)
                _advance(draft, span)
                remaining -= span
                interrupted = _interrupted(draft, actor_id)
            if interrupted:
                verdicts.append(
                    crafting.ruling(
                        "blocked",
                        "The work was interrupted before this step was completed.",
                        [],
                        (draft["sim_time_ms"] - start) // 1000,
                        action=proposal["action"],
                    )
                )
                break
            # Revalidate moving targets and resources at the instant the effect happens.
            verdict = crafting.validate(actors.view(draft, actor_id), proposal)
            verdict["effort_seconds"] = (draft["sim_time_ms"] - start) // 1000
            verdict["walk"] = walk
            verdicts.append(verdict)
            if verdict["category"] != "success":
                break
            before = copy.deepcopy(draft)
            step_deltas = _step_deltas(actors.view(draft, actor_id), run_id, text, verdict, event_id, number, actor_id)
            actors.normalize(step_deltas, actor_id)
            apply_step(draft, step_deltas, actor_id)
            deltas.append(step_deltas)
            if step_deltas["new_objects"]:
                made_by_step[number] = step_deltas["new_objects"][0]["id"]
            step_entry = _step_entry(draft, verdict, step_deltas, event_id, number, text, actor_id)
            observed = perception.perceive(draft, step_entry, before)
            perception.apply_perceptions(draft, observed)
            reputation.after_deed(draft, step_entry)
            step_deltas["observations"] = observed
            _precedent(draft, before, proposal, verdict, text)
        if len(judged["steps"]) > MAX_STEPS and verdicts and verdicts[-1]["category"] == "success":
            verdicts[-1]["notes"].append(f"Only the first {MAX_STEPS} steps were attempted.")
    if not verdicts:
        verdicts.append(crafting.ruling("success", "You already have those materials with you.", []))
    for verdict in verdicts:
        verdict["reason"] = humanize(verdict["reason"], draft, made_by_step)
    committed = [v for v in verdicts if v["category"] == "success"]
    last = verdicts[-1]
    category = "success" if last["category"] == "success" else "partial_success" if committed else last["category"]
    made_ids = [o["id"] for d in deltas for o in d["new_objects"]]
    crafted = next((d["new_objects"][0]["id"] for d, v in zip(deltas, committed) if v["action"] == "make"), None)
    harm = next((v["harm"] for v in reversed(committed) if v["harm"]), None)
    summary = {
        "category": category,
        "action": last["action"],
        "reason": " ".join(v["reason"] for v in verdicts),
        "effort_seconds": sum(v["effort_seconds"] for v in verdicts),
        "notes": [n for v in verdicts for n in v["notes"]]
        if len(verdicts) == 1
        else [f"Step {i}: {n}" for i, v in enumerate(verdicts, 1) for n in v["notes"]],
        "consumed_ids": [i for v in committed for i in v["consumed_ids"]],
        "tool_ids": [i for v in committed for i in v["tool_ids"]],
        "new_spec": next((v["new_spec"] for v in committed if v["new_spec"]), None),
        "take_ids": [i for v in committed for i in v["take_ids"]],
        "transform": next((v["transform"] for v in reversed(committed) if v["transform"]), None),
        "harm": harm,
        "property": [c for v in committed for c in v["property"]],
        "fill": next((v["fill"] for v in reversed(committed) if v["fill"]), None),
        "demonstration": next((v["demonstration"] for v in reversed(committed) if v["demonstration"]), None),
        "give": next((v["give"] for v in reversed(committed) if v["give"]), None),
        "treat": next((v["treat"] for v in reversed(committed) if v.get("treat")), None),
        "install": next((v["install"] for v in reversed(committed) if v["install"]), None),
        "lift_out": next((v["lift_out"] for v in reversed(committed) if v["lift_out"]), None),
        "offer_trade": next((v["offer_trade"] for v in reversed(committed) if v["offer_trade"]), None),
        "gather": next((v["gather"] for v in reversed(committed) if v["gather"]), None),
        "hurt_self": next((v["hurt_self"] for v in reversed(committed) if v.get("hurt_self")), None),
        "precedent_key": (judged or {}).get("precedent_key"),
        "steps": [
            {"action": v["action"], "category": v["category"], "reason": v["reason"], "notes": v["notes"]}
            for v in verdicts
        ],
    }
    transformed = next((d["transformed"] for d in reversed(deltas) if d["transformed"]), None)
    actor = draft["player"] if actor_id == "player" else cast.find(draft["npcs"], actor_id)
    px, py = actor["x"], actor["y"]
    entry = {
        "kind": "craft",
        "actor_id": actor_id,
        "action": summary["action"],
        "text": text,
        "category": category,
        "reason": summary["reason"],
        "steps": summary["steps"],
        "step": {
            "step_id": "step_1",
            "operation_key": "craft",
            "actor_id": actor_id,
            "input_refs": [
                {"existing_entity_id": i}
                for i in summary["consumed_ids"]
                + summary["tool_ids"]
                + summary["take_ids"]
                + ([transformed["id"]] if transformed else [])
            ],
            "output_bindings": made_ids,
            "depends_on": [],
            "required_capabilities": [],
            "required_skill": None,
            "effort_seconds": summary["effort_seconds"],
            "risk_tags": [],
            "status": "completed" if category == "success" else category,
        },
        "player_cell": [px, py],
        "event_id": event_id,
        "made": crafted or (made_ids[0] if made_ids else None),
        "crafted": crafted,
        "made_name": draft["objects"][crafted or made_ids[0]]["name"] if made_ids else None,
        "made_ids": made_ids,
        "taken_ids": summary["take_ids"],
        "transformed": transformed,
        "harm": harm,
        "fill": summary["fill"],
        "demonstration": summary["demonstration"],
        "give": summary["give"],
        "install": summary["install"],
        "lift_out": summary["lift_out"],
        "offer_trade": summary["offer_trade"],
        **(
            {"treated": summary["treat"]} if summary.get("treat") and summary["treat"]["patient_id"] != "player" else {}
        ),
        "walk": [cell for d in deltas for cell in d.get("walk", [])],
        "property": summary["property"],
        "precedent_key": summary["precedent_key"],
        "trace_id": trace_id,
    }
    payload = {
        "steps": deltas,
        "journal_entry": entry,
        "sim_time_ms": draft["sim_time_ms"],
        "journal_added": copy.deepcopy(draft["journal"][len(state["journal"]) :]),
        "world": {
            k: copy.deepcopy(v)
            for k, v in draft.items()
            if k not in ("journal", "last_action", "event_seq", "player_seq", "tick")
        },
    }
    return payload, summary, draft


def apply_payload(state: State, payload: dict) -> None:
    if "world" in payload:
        world = copy.deepcopy(payload["world"])
        for oid, obj in world.pop("objects").items():
            state["objects"].setdefault(oid, {}).update(obj)
        for npc in world.pop("npcs"):
            existing = cast.find(state["npcs"], npc["id"])
            if existing is None:
                state["npcs"].append(npc)
            else:
                existing.clear()
                existing.update(npc)
        state["player"].update(world.pop("player"))
        state.update(world)
        state["journal"].extend(payload.get("journal_added", []))
        state["journal"].append(payload["journal_entry"])
        state["last_action"] = payload["journal_entry"]
        return
    # People first, so wounds and deaths recorded by the steps are applied on top of their movement.
    if "npcs" in payload:
        state["npcs"] = payload["npcs"]
    for deltas in payload["steps"]:
        apply_step(state, deltas)
    state["journal"].append(payload["journal_entry"])
    state["last_action"] = payload["journal_entry"]
    state["sim_time_ms"] = payload["sim_time_ms"]


def _advance(state, elapsed):
    payload = clock.advance_people(state, elapsed)
    store.apply_people(state, payload)
    state["sim_time_ms"] += elapsed


def _interrupted(state, actor_id):
    actor = state["player"] if actor_id == "player" else cast.find(state["npcs"], actor_id)
    return not actor.get("alive", True) or actor.get("down", False) or state.get("subdued_by")


def _step_entry(state, verdict, delta, event, number, text, actor_id):
    made = delta["new_objects"]
    return {
        "kind": "craft",
        "category": verdict["category"],
        "action": verdict["action"],
        "reason": verdict["reason"],
        "text": text,
        "event_id": event,
        "step_number": number,
        "actor_id": actor_id,
        "player_cell": list(
            cast.player_cell(state) if actor_id == "player" else cast.cell(cast.find(state["npcs"], actor_id))
        ),
        "property": verdict["property"],
        "made_ids": [o["id"] for o in made],
        "made_name": made[0]["name"] if made else None,
        **{k: verdict.get(k) for k in ("harm", "demonstration", "give", "install", "lift_out")},
        "treated": verdict.get("treat"),
    }


def _precedent(state, before, proposal, verdict, text):
    refs = set(verdict["consumed_ids"] + verdict["tool_ids"] + verdict["take_ids"])
    # Preserve causal input state, independent of descriptive prose.
    refs.update(proposal.get("resource_ids", []))

    def named(value):
        if isinstance(value, str) and value in before["objects"]:
            refs.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                named(item)
        elif isinstance(value, list):
            for item in value:
                named(item)

    named(proposal)
    people = {p["id"]: p for p in judge_view.people_nearby(before)}
    helper_refs = set(proposal.get("helper_ids", []))
    for operation in ("install", "lift_out"):
        helper_refs.update((proposal.get(operation) or {}).get("aid_ids", []))
    helpers = {i: precedents.helper_fingerprint(people[i]) for i in helper_refs if i in people}
    inputs = {i: copy.deepcopy(before["objects"][i]) for i in sorted(refs) if i in before["objects"]}
    case = {
        "intention": text,
        "proposal": copy.deepcopy(proposal),
        "inputs": inputs,
        "helpers": helpers,
        "outcome": verdict["category"],
        "reason": verdict["reason"],
        "at": state["sim_time_ms"],
    }
    key = proposal.get("precedent_key") or str(len(state.setdefault("precedents", [])))
    case["key"] = key
    state.setdefault("precedents", []).append(case)
