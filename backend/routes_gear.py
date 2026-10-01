"""The stranger's hands and body (D-49): strike, throw, guard, equip, swap hands, treat wounds. All code, no model.

Blows and guarding are "fight" events. Putting things on, changing hands
and treating are "gear" events: they take time, so outside a fight the world moves on by that much; in a fight
the clock is already running, so the hand is simply busy for that long.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

import attempts
import cast
import clock
import combat
import commands
import gear
import library
import perception
import routes_tutorial
import store
import views
from shapes import State, Thing

router = APIRouter(route_class=views.Shown)  # Replies carry their state's view (views.py).


class Strike(BaseModel):
    hand: str = Field(default="right", pattern="^(right|left)$")
    target_id: str | None = Field(default=None, max_length=60)  # Whoever the stranger faces; else the nearest.
    throw: bool = False
    facing: list[float] = Field(default_factory=lambda: [0.0, 1.0], min_length=2, max_length=2)
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


def aim(state: State, wanted: str | None, reach: float, facing: list[float] | None = None) -> str | None:
    """Whoever the stranger aims at (the client picks who they face); else whoever is in front within reach; else
    nobody: the blow goes where they face (D-51: swinging is never refused for want of a target)."""
    npc = cast.find(state["npcs"], wanted or "")
    if npc is not None and npc.get("alive", True):
        return npc["id"]
    ahead = combat.in_front(state, [n for n in state["npcs"] if not combat.down(n)], facing, reach)
    return ahead["id"] if ahead else None


@router.post("/runs/{run_id}/strike")
@commands.answers
def strike(run_id: str, request: Strike):
    """Space (right hand) or F (left): a blow, shot, pour or throw, at someone or at the air, any time. It lands
    after its wind-up, on the clock; this only starts it (D-49: anyone can step out of reach)."""
    with commands.open(run_id, request) as cmd:
        state = cmd.state
        if state["player"].get("down"):
            raise HTTPException(409, {"reason": "down", "message": "You're on the ground and can't."})
        profile, _ = combat.hand_use(state, request.hand)
        target = aim(state, request.target_id, max(profile["reach"], profile.get("range") or 0), request.facing)
        now = state["sim_time_ms"]
        result = (
            combat.throw(state, request.hand, target, now, request.facing)
            if request.throw
            else combat.strike(state, request.hand, target, now, request.facing)
        )
        if not result["ok"]:
            return {"state": state, "duplicate": False, "strike": result}
        cmd.save("fight", state["tick"])
    return {"state": state, "duplicate": False, "strike": {**result, "target_id": target}}


@router.post("/runs/{run_id}/guard")
@commands.answers
def guard(run_id: str, request: Guard):
    """Hold F (or the shield hand's key): the shield goes up facing that way; let go and it comes down."""
    with commands.open(run_id, request) as cmd:
        result = combat.guard(cmd.state, request.raised, request.facing, cmd.state["sim_time_ms"])
        if result["ok"]:
            cmd.save("fight", cmd.state["tick"])
    return {"state": cmd.state, "duplicate": False, "guard": result}


def _gear_event(cmd: commands.Command, seconds: int, journal_line: str | None) -> None:
    """Something done with the stranger's own things, taking this long: outside a fight the world moves on by
    that much; in one, the hands are busy for it."""
    state = cmd.state
    if journal_line:
        state["journal"].append({"kind": "gear", "category": "success", "reason": journal_line})
    if combat.active(state):
        ready = state["player"].setdefault("ready_at", {}) if isinstance(state["player"].get("ready_at"), dict) else {}
        state["player"]["ready_at"] = ready
        for hand in gear.HAND_SLOTS:
            ready[hand] = max(ready.get(hand, 0), state["sim_time_ms"] + seconds * 1000)
    elif seconds > 0:
        people = clock.advance_people(state, seconds * 1000)
        state["npcs"] = people["npcs"]
        state["sim_time_ms"] += seconds * 1000
        store.apply_people(state, people)
    cmd.save("gear")
    routes_tutorial.progress(cmd)  # The tutorial may move on (D-50).


@router.post("/runs/{run_id}/equip")
@commands.answers
def equip(run_id: str, request: Equip, background: BackgroundTasks):
    """Put something on or in a hand (slot), or take it off (no slot). Code only. Something that has never been
    drawn held or worn gets that picture now (from the item library if it's been painted before)."""
    with commands.open(run_id, request) as cmd:
        state = cmd.state
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
        _gear_event(cmd, result["seconds"], None)
        if view:
            attempts.queue_picture(
                cmd.connection, run_id, obj, view, obj[f"{view}_asset_id"], library.signature(obj), background
            )
    return {"state": state, "duplicate": False, "equip": result}


def _picture_needed(obj: Thing, slot: str | None) -> str | None:
    """held or worn, if this thing is going somewhere it has never been drawn (and isn't drawn by the painting)."""
    if slot is None or obj.get("no_overlay"):
        return None
    if slot in gear.HAND_SLOTS and not obj.get("held_asset_id"):
        return "held"
    if slot in gear.BODY_SLOTS and not obj.get("worn_asset_id"):
        return "worn"
    return None


@router.post("/runs/{run_id}/swap")
@commands.answers
def swap(run_id: str, request: Swap):
    """X: what's in each hand changes places."""
    with commands.open(run_id, request) as cmd:
        result = gear.swap_hands(cmd.state, cmd.state["player"])
        if result["ok"]:
            _gear_event(cmd, result["seconds"], None)
    return {"state": cmd.state, "duplicate": False, "swap": result}


@router.post("/runs/{run_id}/treat")
@commands.answers
def treat(run_id: str, request: Treat):
    """Bind, stitch, splint, dress or poultice a condition: the stranger's own, or someone within reach."""
    with commands.open(run_id, request) as cmd:
        state = cmd.state
        # Allowed mid-fight too (D-51): it takes the hands for as long as it takes, and blows keep coming.
        remedy = state["objects"].get(request.object_id)
        if remedy is None or remedy.get("holder_id") != "player":
            return {"state": state, "duplicate": False, "treat": {"ok": False, "reason": "You don't have that."}}
        patient = state["player"] if request.patient_id == "player" else cast.find(state["npcs"], request.patient_id)
        if patient is None or not patient.get("alive", True):
            return {"state": state, "duplicate": False, "treat": {"ok": False, "reason": "There's nobody to treat."}}
        if patient is not state["player"] and cast.distance(patient, state["player"]) > 2.5:
            return {
                "state": state,
                "duplicate": False,
                "treat": {"ok": False, "reason": f"You need to be beside {patient['name']}."},
            }
        condition = (
            (patient.get("conditions") or [])[request.condition]
            if request.condition < len(patient.get("conditions") or [])
            else None
        )
        now = state["sim_time_ms"]
        result = gear.treat(patient, request.condition, remedy, now)
        if not result["ok"]:
            return {"state": state, "duplicate": False, "treat": result}
        if result["consumed"]:
            state["objects"][remedy["id"]] = {**remedy, "holder_id": "used", "condition": "used up"}
        if patient is not state["player"]:  # Help, seen and remembered (D-49): like a gift.
            entry = {
                "event_id": state["event_seq"] + 1,
                "category": "success",
                "action": "treat",
                "property": [],
                "treated": {
                    "patient_id": patient["id"],
                    "patient_name": patient["name"],
                    "what": gear.describe(condition or {}).removeprefix("the "),
                    "remedy": gear.REMEDIES[gear.of(remedy)["class"]]["name"],
                },
            }
            perception.apply_perceptions(state, perception.perceive(state, entry))
            result["text"] = (
                result["text"]
                .replace("You treat the", f"You treat {patient['name']}'s")
                .replace(f"{patient['name']}'s the", f"{patient['name']}'s")
            )
        _gear_event(cmd, result["seconds"], result["text"])
    return {"state": state, "duplicate": False, "treat": result}
