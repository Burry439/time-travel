"""The stranger's hands and body (D-49): strike, throw, guard, equip, swap hands, treat wounds. All code, no model.

Blows and guarding are "fight" events (the resulting fields, like a punch was). Putting things on, changing hands
and treating are "gear" events: they take time, so outside a fight the world moves on by that much; in a fight
the clock is already running, so the hand is simply busy for that long.
"""
from __future__ import annotations

import math

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

import attempts
import combat
import gear
import library
import minds
import routes_world
import store

router = APIRouter()


class Strike(BaseModel):
    hand: str = Field(default="right", pattern="^(right|left)$")
    target_id: str | None = Field(default=None, max_length=60)  # Whoever the stranger faces; else the nearest.
    throw: bool = False
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class Guard(BaseModel):
    raised: bool
    facing: list[float] = Field(default_factory=lambda: [0.0, 1.0], min_length=2, max_length=2)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class Equip(BaseModel):
    object_id: str = Field(min_length=1, max_length=80)
    slot: str | None = Field(default=None, max_length=12)  # None takes it off.
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class Swap(BaseModel):
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class Treat(BaseModel):
    object_id: str = Field(min_length=1, max_length=80)  # The remedy.
    patient_id: str = Field(default="player", max_length=60)
    condition: int = Field(ge=0, le=20)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


def _open(connection, run_id: str, request) -> tuple[dict, dict, dict | None]:
    run, state = store.load_run(connection, run_id)
    prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
    if prior_seq is not None:
        return run, state, {"state": store.state_at(connection, run, prior_seq), "duplicate": True}
    if state["inside_city"] or not state["player"]["alive"]:
        raise HTTPException(409, "Run is no longer interactive")
    return run, state, None


def aim(state: dict, wanted: str | None, reach: float) -> str | None:
    """Whoever the stranger aims at if they can; else the nearest attacker; else whoever is within reach."""
    npc = minds.find(state["npcs"], wanted or "")
    if npc is not None and npc.get("alive", True):
        return npc["id"]
    here = minds.player_cell(state)
    fighters = [minds.find(state["npcs"], a) for a in (combat.active(state) or {}).get("attackers", [])]
    fighters = [f for f in fighters if f is not None and not combat.down(f)]
    if not fighters:
        fighters = [n for n in state["npcs"] if n.get("alive", True) and not combat.down(n)
                    and math.dist(minds._cell(n), here) <= reach]
    if not fighters:
        return None
    return min(fighters, key=lambda f: math.dist(minds._cell(f), here))["id"]


@router.post("/runs/{run_id}/strike")
def strike(run_id: str, request: Strike):
    """Space (right hand) or F (left): a blow, shot, pour or throw at someone. It lands after its wind-up, on the
    clock; this only starts it (D-49: anyone can step out of reach)."""
    with store.lock, store.db() as connection:
        run, state, prior = _open(connection, run_id, request)
        if prior:
            return prior
        if state["player"].get("down"):
            raise HTTPException(409, {"reason": "down", "message": "You're on the ground and can't."})
        profile, _ = combat.hand_use(state, request.hand)
        target = aim(state, request.target_id, max(profile["reach"], profile.get("range") or 0))
        if target is None:
            raise HTTPException(409, {"reason": "no_target", "message": "There's nobody there to hit."})
        now = state["sim_time_ms"]
        result = combat.throw(state, request.hand, target, now) if request.throw else \
            combat.strike(state, request.hand, target, now)
        if not result["ok"]:
            return {"state": state, "duplicate": False, "strike": result}
        journal_before = len(state["journal"])
        routes_world.fight_event(connection, state, journal_before, request.request_id,
                                 {"strike": {"target_id": target, "hand": request.hand}})
    return {"state": state, "duplicate": False, "strike": {**result, "target_id": target}}


@router.post("/runs/{run_id}/guard")
def guard(run_id: str, request: Guard):
    """Hold F (or the shield hand's key): the shield goes up facing that way; let go and it comes down."""
    with store.lock, store.db() as connection:
        run, state, prior = _open(connection, run_id, request)
        if prior:
            return prior
        result = combat.guard(state, request.raised, request.facing, state["sim_time_ms"])
        if result["ok"]:
            routes_world.fight_event(connection, state, len(state["journal"]), request.request_id,
                                     {"guard": {"raised": request.raised}})
    return {"state": state, "duplicate": False, "guard": result}


def _gear_event(connection, state: dict, request_id: str, seconds: int, journal_line: str | None,
                extra: dict | None = None) -> None:
    """Something done with the stranger's own things, taking this long: outside a fight the world moves on by
    that much; in one, the hands are busy for it."""
    payload: dict = {"player": state["player"], "objects": state["objects"], "npcs": state["npcs"]}
    if journal_line:
        entry = {"kind": "gear", "category": "success", "reason": journal_line}
        state["journal"].append(entry)
        payload["journal_added"] = [entry]
    if combat.active(state):
        ready = state["player"].setdefault("ready_at", {}) if isinstance(state["player"].get("ready_at"), dict) else {}
        state["player"]["ready_at"] = ready
        for hand in gear.HAND_SLOTS:
            ready[hand] = max(ready.get(hand, 0), state["sim_time_ms"] + seconds * 1000)
        payload["player"] = state["player"]
    elif seconds > 0:
        people = store.advance_people(state, seconds * 1000)
        payload.update(people)
        payload["sim_time_ms"] = state["sim_time_ms"] + seconds * 1000
    payload.update(extra or {})
    store.append(connection, state, "gear", payload, request_id, payload.get("sim_time_ms", state["sim_time_ms"]) // 1000)
    store.apply_gear(state, payload, already_journaled=True)


@router.post("/runs/{run_id}/equip")
def equip(run_id: str, request: Equip, background: BackgroundTasks):
    """Put something on or in a hand (slot), or take it off (no slot). Code only. Something that has never been
    drawn held or worn gets that picture now (from the item library if it's been painted before)."""
    with store.lock, store.db() as connection:
        run, state, prior = _open(connection, run_id, request)
        if prior:
            return prior
        obj = state["objects"].get(request.object_id)
        if obj is None:
            raise HTTPException(404, "Unknown object")
        result = gear.equip(state, state["player"], obj, request.slot, fighting=bool(combat.active(state)))
        if not result["ok"]:
            return {"state": state, "duplicate": False, "equip": result}
        if "gear" not in obj:  # From before D-49: fix code's reading of it on the thing, so everyone sees the same.
            state["objects"][obj["id"]] = obj = {**obj, "gear": gear.classify(obj)}
        view = _picture_needed(obj, request.slot)
        if view:
            state["objects"][obj["id"]] = obj = {**obj, f"{view}_asset_id": f"spr_{run_id[:8]}_{obj['id']}_{view}"}
        _gear_event(connection, state, request.request_id, result["seconds"], None,
                    {"equip": {"object_id": obj["id"], "slot": request.slot}})
        if view:
            attempts.queue_picture(connection, run_id, obj, view, obj[f"{view}_asset_id"], library.signature(obj),
                                   background)
    return {"state": state, "duplicate": False, "equip": result}


def _picture_needed(obj: dict, slot: str | None) -> str | None:
    """held or worn, if this thing is going somewhere it has never been drawn (and isn't drawn by the painting)."""
    if slot is None or obj.get("no_overlay"):
        return None
    if slot in gear.HAND_SLOTS and not obj.get("held_asset_id"):
        return "held"
    if slot in gear.BODY_SLOTS and not obj.get("worn_asset_id"):
        return "worn"
    return None


@router.post("/runs/{run_id}/swap")
def swap(run_id: str, request: Swap):
    """X: what's in each hand changes places."""
    with store.lock, store.db() as connection:
        run, state, prior = _open(connection, run_id, request)
        if prior:
            return prior
        result = gear.swap_hands(state, state["player"])
        if result["ok"]:
            _gear_event(connection, state, request.request_id, result["seconds"], None, {"swap": True})
    return {"state": state, "duplicate": False, "swap": result}


@router.post("/runs/{run_id}/treat")
def treat(run_id: str, request: Treat):
    """Bind, stitch, splint, dress or poultice a condition: the stranger's own, or someone within reach."""
    with store.lock, store.db() as connection:
        run, state, prior = _open(connection, run_id, request)
        if prior:
            return prior
        if combat.active(state):
            return {"state": state, "duplicate": False,
                    "treat": {"ok": False, "reason": "Not while someone is trying to kill you."}}
        remedy = state["objects"].get(request.object_id)
        if remedy is None or remedy.get("holder_id") != "player":
            return {"state": state, "duplicate": False, "treat": {"ok": False, "reason": "You don't have that."}}
        patient = state["player"] if request.patient_id == "player" else minds.find(state["npcs"], request.patient_id)
        if patient is None or not patient.get("alive", True):
            return {"state": state, "duplicate": False, "treat": {"ok": False, "reason": "There's nobody to treat."}}
        if patient is not state["player"] and math.dist(minds._cell(patient), minds.player_cell(state)) > 2.5:
            return {"state": state, "duplicate": False,
                    "treat": {"ok": False, "reason": f"You need to be beside {patient['name']}."}}
        condition = (patient.get("conditions") or [])[request.condition] if request.condition < len(
            patient.get("conditions") or []) else None
        now = state["sim_time_ms"]
        result = gear.treat(patient, request.condition, remedy, now)
        if not result["ok"]:
            return {"state": state, "duplicate": False, "treat": result}
        if result["consumed"]:
            state["objects"][remedy["id"]] = {**remedy, "holder_id": "used", "condition": "used up"}
        extra: dict = {"treat": {"patient_id": request.patient_id, "object_id": remedy["id"]}}
        if patient is not state["player"]:  # Help, seen and remembered (D-49): like a gift.
            entry = {"event_id": state["event_seq"] + 1, "category": "success", "action": "treat", "property": [],
                     "treated": {"patient_id": patient["id"], "patient_name": patient["name"],
                                 "what": gear.describe(condition or {}).removeprefix("the "),
                                 "remedy": gear.REMEDIES[gear.of(remedy)["class"]]["name"]}}
            minds.apply_perceptions(state, minds.perceive(state, entry))
            result["text"] = result["text"].replace("You treat the", f"You treat {patient['name']}'s").replace(
                f"{patient['name']}'s the", f"{patient['name']}'s")
        _gear_event(connection, state, request.request_id, result["seconds"], result["text"], extra)
    return {"state": state, "duplicate": False, "treat": result}
