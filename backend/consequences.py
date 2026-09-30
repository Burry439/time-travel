"""A ruled attempt becomes the world: each step validated against the world as it is by then, what it makes,
changes, moves or hurts worked out as changes, applied in order, and stopped at the first step that
doesn't succeed (GDD 6.2). Models propose; this is where what they proposed happens."""

from __future__ import annotations

import copy
import re

import content
import crafting
import gear
import heat
import m2
import paths
import tuning

CONTENT = content.MATERIALS


MAX_STEPS = 4


OPERATION_CAPABILITIES = {"tieable": "tie", "container": "fill"}


def gate_after(state: dict, fixture_id: str, barred: bool) -> dict | None:
    """The gate stands open while nothing bars it (or the stranger has been let in); None if unaffected."""
    if fixture_id != m2.GATE_FIXTURE or state.get("seed_version", 0) < m2.GATE_BAR_SEED:
        return None
    return {"open": bool(state.get("admitted")) or not barred, **({} if barred else {"unbarred_by": "player"})}


def _known_after(obj: dict, results: list[dict], event_id: int) -> list[dict]:
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


def _step_deltas(state: dict, run_id: str, text: str, verdict: dict, event_id: int, number: int) -> dict:
    """World changes for one validated step; ids stay unique across the steps of one attempt."""
    suffix = "" if number == 1 else f"_{number}"
    walk = verdict.get("walk") or []
    px, py = walk[-1] if walk else (state["player"]["x"], state["player"]["y"])
    new_objects, consumed, taken, transformed, npc_updates, moved = [], [], [], None, [], []
    water, known, given, spilled, installed, trade, lifted, gate = [], None, None, 0.0, None, None, None, None
    if verdict["action"] == "make":
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
        new_objects.append(
            _object(
                f"made_{event_id}{suffix}",
                run_id,
                spec,
                px,
                py,
                "player",
                "player" if fits else None,
                text,
                event_id,
                consumed,
                verdict["tool_ids"],
            )
        )
        if spec.get("burning"):  # A fire: it stays where it was lit and burns down with its fuel.
            span = max(
                tuning.FIRE_MS_RANGE[0], min(tuning.FIRE_MS_RANGE[1], int(spec["mass_kg"] * tuning.FIRE_MS_PER_KG))
            )
            new_objects[-1].update(
                burning=True,
                feature="fire",
                capabilities=[],
                holder_id=None,
                burns_until=state["sim_time_ms"] + verdict["effort_seconds"] * 1000 + span,
            )
        # Water in anything built in stays in the new thing if it holds water; otherwise it spills.
        held = round(sum(state["objects"][i].get("water_l", 0.0) for i in consumed), 3)
        kept = min(held, spec.get("capacity_l") or 0.0) if "container" in spec["flags"] else 0.0
        new_objects[-1]["water_l"] = kept
        spilled = round(held - kept, 3)
    elif verdict["action"] == "take":
        taken = verdict["take_ids"]
    elif verdict["action"] == "gather":  # New small things in hand; the source stays as it was.
        plan = verdict["gather"]
        source = state["objects"][plan["source_id"]]
        owner = source["owner_id"] if source["owner_id"] not in (None, "player") else "player"
        asset_id = None
        for index in range(1, plan["piece"]["count"] + 1):
            obj = _object(
                f"gathered_{event_id}{suffix}_{index}",
                run_id,
                plan["piece"],
                px,
                py,
                owner,
                "player",
                text,
                event_id,
                [plan["source_id"]],
                verdict["tool_ids"],
                asset_id,
            )
            asset_id = obj["sprite_asset_id"]  # Identical pieces share one painting.
            new_objects.append(obj)
        if "carry" in source["capabilities"]:  # A small source is that much smaller; a tree doesn't notice.
            left = max(0.01, round(source["mass_kg"] - plan["piece"]["mass_kg"] * plan["piece"]["count"], 3))
            water = [{"id": source["id"], "mass_kg": left}]
    elif verdict["action"] == "treat":
        treated = verdict["treat"]
        if treated["patient_id"] == "player":
            water.append({"id": "__player__", "conditions": treated["conditions"]})
        else:
            npc_updates.append({"id": treated["patient_id"], "conditions": treated["conditions"]})
        if treated["consumed"]:
            moved.append({"id": treated["consumed"], "used_up": True})
    elif verdict["action"] == "equip":
        water.append({"id": "__player__", "equipped": verdict["equip"]["equipped"]})
    elif verdict["action"] == "drop":
        moved = [{"id": i, "x": px, "y": py} for i in verdict["drop_ids"]]  # At the stranger's feet.
    elif verdict["action"] == "transform":
        plan = verdict["transform"]
        target = state["objects"][plan["target_id"]]
        cleared = paths.cleared_obstacles(state) | ({target["geometry_name"]} if target.get("geometry_name") else set())
        in_hand = target["holder_id"] == "player"
        load = m2.inventory_mass(state) - (target["mass_kg"] if in_hand else 0)
        total = sum(p["count"] for p in plan["pieces"])
        cells = iter(
            paths.open_cells_near(state, px if in_hand else target["x"], py if in_hand else target["y"], cleared, total)
        )
        index = 0
        for piece in plan["pieces"]:
            asset_id = None
            for _ in range(piece["count"]):
                index += 1
                keep = in_hand and load + piece["mass_kg"] <= tuning.CARRY_LIMIT_KG
                load += piece["mass_kg"] if keep else 0
                x, y = next(cells)
                obj = _object(
                    f"piece_{event_id}{suffix}_{index}",
                    run_id,
                    piece,
                    x,
                    y,
                    "player" if target["owner_id"] == "player" else target["owner_id"],
                    "player" if keep else None,
                    text,
                    event_id,
                    [plan["target_id"]],
                    verdict["tool_ids"],
                    asset_id,
                )
                asset_id = obj["sprite_asset_id"]  # Identical pieces share one painting.
                new_objects.append(obj)
        transformed = {
            "id": plan["target_id"],
            "result_state": plan["result_state"],
            "into": [o["id"] for o in new_objects],
        }
    elif verdict["action"] == "harm":
        harm = verdict["harm"]
        npc = next(n for n in state["npcs"] if n["id"] == harm["target_id"])
        if "effective" in harm:  # D-49: what gear.hit worked out, carried out on the person.
            body = {k: copy.deepcopy(npc.get(k)) for k in ("id", "health", "alive", "down", "conditions")}
            body["health"] = body["health"] if body["health"] is not None else 100
            body["alive"] = body["alive"] if body["alive"] is not None else True
            body["conditions"] = body["conditions"] or []
            if harm["result"] not in ("missed", "deflected"):
                gear.apply(body, harm, state["sim_time_ms"])
            health, down = body["health"], bool(body.get("down"))
            if harm["result"] == "killed":
                health = 0
            injuries = npc.get("injuries", []) + (
                [harm["injury"]] if harm["result"] not in ("missed", "deflected") else []
            )
            npc_updates.append(
                {
                    "id": npc["id"],
                    "alive": health > 0,
                    "health": health,
                    "injuries": injuries,
                    "conditions": body["conditions"],
                    **({"down": True} if down and health > 0 else {}),
                }
            )
        else:  # Older journeys' events (before D-49): fixed damage by result.
            health = npc.get("health", 100)
            down = bool(npc.get("down"))
            if harm["result"] == "killed":
                health = 0
            elif harm["result"] == "disabled":
                health, down = min(health, tuning.DISABLED_HEALTH), True
            elif harm["result"] == "wounded":
                health = max(0, health - tuning.WOUND_DAMAGE)
                if health == 0:
                    harm["result"] = "killed"
                    verdict["reason"] = verdict["reason"].rstrip() + f" {npc['name']} does not survive this wound."
                    verdict["notes"].append("Wound was fatal: the injuries added up (health reached 0).")
            injuries = npc.get("injuries", []) + (
                [harm["injury"]] if harm["result"] not in ("missed", "deflected") else []
            )
            npc_updates.append(
                {
                    "id": npc["id"],
                    "alive": health > 0,
                    "health": health,
                    "injuries": injuries,
                    **({"down": True} if down and health > 0 else {}),
                }
            )
        if harm["result"] == "killed" and "effective" in harm and not verdict["reason"].rstrip().endswith("."):
            verdict["reason"] = verdict["reason"].rstrip() + "."
        taken = verdict["take_ids"]  # A weapon picked up on the way.
        if harm["method"] == "thrown" and harm["weapon_id"]:
            x, y = paths.open_cells_near(state, npc["x"], npc["y"], paths.cleared_obstacles(state), 1)[0]
            moved.append({"id": harm["weapon_id"], "x": x, "y": y})
        if harm["method"] == "poured" and harm["weapon_id"]:  # Emptied over them.
            spilled = state["objects"][harm["weapon_id"]].get("water_l", 0.0)
            water = [{"id": harm["weapon_id"], "water_l": 0.0, "temperature": "cold", "heated_at": None}]
    elif verdict["action"] == "fill":
        fill = verdict["fill"]
        container, source = state["objects"][fill["container_id"]], state["objects"][fill["source_id"]]
        water = [
            {"id": container["id"], "water_l": round(container.get("water_l", 0.0) + fill["litres"], 3)},
            {"id": source["id"], "water_l": round(source["water_l"] - fill["litres"], 3)},
        ]
    elif verdict["action"] == "change":
        change = verdict["change"]
        water = [{"id": change["id"], **change["fields"]}] + change["pour"]
        spilled = change["spilled_l"]
    elif verdict["action"] == "demonstrate":
        shown = verdict["demonstration"]
        known = {
            "id": shown["object_id"],
            "known_capabilities": _known_after(state["objects"][shown["object_id"]], shown["results"], event_id),
        }
    elif verdict["action"] == "install":
        plan = verdict["install"]
        into = state["objects"][plan["into_id"]]
        installed = {"id": plan["object_id"], "into": plan["into_id"], "x": into["x"], "y": into["y"]}
        gate = gate_after(state, plan["into_id"], barred=True)
    elif verdict["action"] == "lift_out":
        plan = verdict["lift_out"]
        fixture = state["objects"][plan["from_id"]]
        x, y = paths.open_cells_near(state, fixture["x"], fixture["y"] + 2, paths.cleared_obstacles(state), 1)[0]
        lifted = {"id": plan["object_id"], "x": x, "y": y}
        gate = gate_after(state, plan["from_id"], barred=False)
    elif verdict["action"] == "offer_trade":
        trade = {
            **verdict["offer_trade"],
            "id": f"trade_{event_id}{suffix}",
            "status": "offered",
            "offered_event": event_id,
        }
    elif verdict["action"] == "give":
        give = verdict["give"]
        # A gift of your own (or unowned) thing makes it theirs; someone else's thing stays theirs.
        given = {
            "ids": give["item_ids"],
            "to": give["recipient_id"],
            "owners": {
                i: give["recipient_id"]
                if state["objects"][i]["owner_id"] in (None, "player")
                else state["objects"][i]["owner_id"]
                for i in give["item_ids"]
            },
        }
    deltas = {
        "consumed_ids": consumed,
        "new_objects": new_objects,
        "taken_ids": taken,
        "transformed": transformed,
        "npc_updates": npc_updates,
        "moved": moved,
        "walk": walk,
        "player_to": [px, py] if walk else None,
    }
    deltas.update(
        {
            k: v
            for k, v in (
                ("water", water),
                ("capabilities", known),
                ("given", given),
                ("spilled_l", spilled),
                ("installed", installed),
                ("trade", trade),
                ("lifted_out", lifted),
            )
            if v
        }
    )
    if gate is not None:
        deltas["gate"] = gate
    return deltas


def apply_step(state: dict, deltas: dict) -> None:
    if deltas.get("player_to"):
        state["player"].update(x=deltas["player_to"][0], y=deltas["player_to"][1])
    for landed in deltas.get("moved", []):
        if landed.get("used_up"):  # A bandage or poultice, used (D-49).
            state["objects"][landed["id"]].update(holder_id="used", condition="used up")
            continue
        state["objects"][landed["id"]].update(x=landed["x"], y=landed["y"], holder_id=None)
    new_objects = deltas.get("new_objects") or ([deltas["new_object"]] if deltas.get("new_object") else [])
    if new_objects:
        for item_id in deltas["consumed_ids"]:
            # Its water went into the new thing (or spilled): see _step_deltas.
            state["objects"][item_id].update(holder_id=f"in:{new_objects[0]['id']}", water_l=0.0)
        for obj in new_objects:
            state["objects"][obj["id"]] = obj
            heat.rename(obj)
    for item_id in deltas.get("taken_ids", []):
        state["objects"][item_id]["holder_id"] = "player"
    for change in deltas.get("water", []):  # Water moved, heated, poured; any change of state in place.
        if change["id"] == "__player__":  # The stranger's own body and kit (D-49).
            state["player"].update(copy.deepcopy({k: v for k, v in change.items() if k != "id"}))
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
        state["objects"][item_id].update(holder_id=given["to"], owner_id=given["owners"][item_id])
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
        elif update.get("injury"):  # Seed-5 payloads before multi-step recorded one injury at a time.
            npc.setdefault("injuries", []).append(update["injury"])
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


def humanize(text: str, state: dict, made_by_step: dict[int, str]) -> str:
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
    state: dict, run_id: str, text: str, judged: dict | None, service_error: str | None, trace_id: str, now_ms: int
) -> tuple[dict, dict, dict]:
    """Validate and apply the judge's steps in order on a draft world; stop at the first that fails.

    Returns (event payload, summary verdict for the trace, draft state after the committed steps).
    """
    event_id = state["event_seq"] + 1
    draft = copy.deepcopy(state)
    verdicts, deltas, made_by_step = [], [], {}
    if judged is None:
        verdicts.append(crafting.validate(draft, None, service_error))
    elif judged.get("clarifying_question"):
        verdicts.append(crafting.ruling("needs_clarification", judged["clarifying_question"], []))
    elif not judged.get("steps"):
        verdicts.append(crafting.unresolved([], "the judge returned no steps"))
    else:
        for number, step in enumerate(judged["steps"][:MAX_STEPS], 1):
            verdict = crafting.validate(draft, _resolve_references(step, made_by_step))
            verdicts.append(verdict)
            if verdict["category"] != "success":
                break
            step_deltas = _step_deltas(draft, run_id, text, verdict, event_id, number)
            apply_step(draft, step_deltas)
            deltas.append(step_deltas)
            if step_deltas["new_objects"]:
                made_by_step[number] = step_deltas["new_objects"][0]["id"]
        if len(judged["steps"]) > MAX_STEPS and verdicts[-1]["category"] == "success":
            verdicts[-1]["notes"].append(f"Only the first {MAX_STEPS} steps were attempted.")
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
        "precedent_key": (judged or {}).get("precedent_key"),
        "steps": [
            {"action": v["action"], "category": v["category"], "reason": v["reason"], "notes": v["notes"]}
            for v in verdicts
        ],
    }
    transformed = next((d["transformed"] for d in reversed(deltas) if d["transformed"]), None)
    px, py = state["player"]["x"], state["player"]["y"]
    entry = {
        "kind": "craft",
        "action": summary["action"],
        "text": text,
        "category": category,
        "reason": summary["reason"],
        "steps": summary["steps"],
        "step": {
            "step_id": "step_1",
            "operation_key": "craft",
            "actor_id": "player",
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
    payload = {"steps": deltas, "journal_entry": entry, "sim_time_ms": now_ms + summary["effort_seconds"] * 1000}
    return payload, summary, draft


def apply_payload(state: dict, payload: dict) -> None:
    # People first, so wounds and deaths recorded by the steps are applied on top of their movement.
    if "npcs" in payload:
        state["npcs"] = payload["npcs"]
    for deltas in payload.get("steps", [payload]):  # Older events are one step.
        apply_step(state, deltas)
    state["journal"].append(payload["journal_entry"])
    state["last_action"] = payload["journal_entry"]
    state["sim_time_ms"] = payload["sim_time_ms"]
