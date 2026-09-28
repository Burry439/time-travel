"""Journeys, walking, the exploration clock, rewinding, and the developer's gate switch."""
from __future__ import annotations

import copy
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import combat
import crafting
import encounter
import minds
import store
from ai import config as ai_config, decider

router = APIRouter()


class NewRun(BaseModel):
    mode: str = "normal"


class Move(BaseModel):
    x: int | None = Field(default=None, ge=0, le=95)
    y: int | None = Field(default=None, ge=0, le=71)
    cells: list[list[int]] | None = Field(default=None, min_length=1, max_length=24)  # Several steps at once.
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)
    running: bool = False


class ExploreClock(BaseModel):
    elapsed_ms: int = Field(ge=1, le=1000)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class Strike(BaseModel):
    target_id: str | None = Field(default=None, max_length=60)  # Whoever the stranger faces; else the nearest.
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class FightCommand(BaseModel):
    npc_ids: list[str] = Field(min_length=1, max_length=6)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class GateCommand(BaseModel):
    open: bool
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


@router.get("/health")
def health():
    with store.db() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "seed_version": store.SEED_VERSION, "geometry_version": store.GEOMETRY_VERSION,
            "ai": {**ai_config.status(), **decider.status()}}


@router.post("/runs", status_code=201)
def create_run(request: NewRun):
    if request.mode not in ("normal", "developer"):
        raise HTTPException(422, "Mode must be normal or developer")
    run_id = uuid4().hex
    with store.lock, store.db() as connection:
        connection.execute(
            "INSERT INTO runs (id,mode,seed_version,geometry_version) VALUES (?,?,?,?)",
            (run_id, request.mode, store.SEED_VERSION, store.GEOMETRY_VERSION),
        )
        _, state = store.load_run(connection, run_id)
    return state


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    with store.db() as connection:
        _, state = store.load_run(connection, run_id)
    return state


@router.get("/runs/{run_id}/events")
def get_events(run_id: str):
    with store.db() as connection:
        store.load_run(connection, run_id)
        rows = connection.execute("SELECT seq,tick,kind,payload,request_id FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
    return [{"seq": row["seq"], "tick": row["tick"], "kind": row["kind"],
             "payload": json.loads(row["payload"]), "request_id": row["request_id"]} for row in rows]


@router.post("/runs/{run_id}/checkpoint")
def checkpoint(run_id: str):
    with store.lock, store.db() as connection:
        _, state = store.load_run(connection, run_id)
        connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                           (run_id, state["event_seq"], json.dumps(state, sort_keys=True)))
    return {"event_seq": state["event_seq"], "saved": True}


@router.post("/runs/{run_id}/rewind", status_code=201)
def rewind(run_id: str):
    """Copy this journey up to its last calm moment into a new run, leaving the original untouched."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        point = int(state.get("safe_seq", 0))
        new_id = uuid4().hex
        connection.execute("INSERT INTO runs (id,mode,seed_version,geometry_version) VALUES (?,?,?,?)",
                           (new_id, run["mode"], run["seed_version"], run["geometry_version"]))
        connection.execute("INSERT INTO events (run_id,seq,tick,kind,payload,request_id) "
                           "SELECT ?,seq,tick,kind,payload,request_id FROM events WHERE run_id=? AND seq<=?",
                           (new_id, run_id, point))
        _, restored = store.load_run(connection, new_id)
    return restored


@router.post("/runs/{run_id}/move")
def move(run_id: str, request: Move):
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            objective = connection.execute(
                "SELECT seq FROM events WHERE run_id=? AND request_id=?",
                (run_id, f"objective:{request.request_id}"),
            ).fetchone()
            end_seq = int(objective["seq"]) if objective else prior_seq
            return {"state": store.state_at(connection, run, end_seq), "duplicate": True}
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer movable")
        if encounter.hostile(state):
            raise HTTPException(409, {"reason": "encounter_active", "state": state})
        cells = request.cells or ([[request.x, request.y]] if request.x is not None and request.y is not None else [])
        if not cells or any(len(cell) != 2 for cell in cells):
            raise HTTPException(422, "Send x and y, or a list of [x, y] cells")

        # Open because its bar was lifted off (not the captain's word, not the developer switch): a guard in the gap.
        holder = combat.gate_held_by(state) if state["gate_open"] and not crafting.m2.gate_barred(state) else None

        def passable(x: int, y: int) -> bool:
            if not (0 <= x <= 95 and 0 <= y <= 71):
                return False
            if 4 <= y <= 8:
                return 46 <= x <= 50 and state["gate_open"] and holder is None
            cleared = crafting.cleared_obstacles(state)  # e.g. felled trees
            for building in store.WORLD_GEOMETRY["buildings"] + store.WORLD_GEOMETRY["obstacles"]:
                if building["name"] in cleared:
                    continue
                bx, by, width, height = building["cells"]
                if bx <= x < bx + width and by <= y < by + height:
                    return False
            return True

        # Walk the cells in order; stop at the first illegal step, keeping the legal ones before it.
        x, y = state["player"]["x"], state["player"]["y"]
        accepted: list[list[int]] = []
        problem = None
        for nx, ny in cells:
            dx, dy = nx - x, ny - y
            if max(abs(dx), abs(dy)) != 1:
                problem = (422, "Move must cross exactly one adjacent cell")
            elif not passable(nx, ny):
                problem = (403, f"{holder['name']} steps into the gateway and bars your way."
                           if holder and 4 <= ny <= 8 and 46 <= nx <= 50
                           else "A building, city wall, or closed gate blocks the path")
            elif dx and dy and (not passable(x + dx, y) or not passable(x, y + dy)):
                problem = (403, "Cannot cut diagonally through a blocked corner")
            if problem:
                break
            x, y = nx, ny
            accepted.append([x, y])
            if y <= 3:
                break  # Inside the city.
        if not accepted:
            raise HTTPException(*problem)
        sim_time_ms = state["sim_time_ms"]  # Walking takes no clock time: the exploration clock runs alongside.
        tick = sim_time_ms // 1000  # One simulation tick is one second.
        payload = {"x": x, "y": y, "running": request.running, "sim_time_ms": sim_time_ms}
        if encounter.active(state):  # A conversation doesn't follow the stranger: walking off ends it for them.
            moved = copy.deepcopy(state)
            moved["player"].update(x=x, y=y)
            encounter.prune(moved)
            if moved.get("encounter") != state.get("encounter"):
                payload.update(encounter=moved.get("encounter"), npcs=moved["npcs"],
                               pending_minds=moved.get("pending_minds", []))
        if len(accepted) > 1:
            payload["path"] = accepted
        store.append(connection, state, "move", payload, request.request_id, tick)
        state["sim_time_ms"] = sim_time_ms
        state["player"].update(x=x, y=y)
        if "encounter" in payload:
            state.update(encounter=payload["encounter"], npcs=payload["npcs"], pending_minds=payload["pending_minds"])
        if y <= 3 and not state["inside_city"]:
            how = "admitted" if state.get("admitted") else "unbarred" if state.get("gate_unbarred_by") else "other"
            store.append(connection, state, "objective_complete", {"location": "loc_city_interior", "how": how},
                         f"objective:{request.request_id}", tick)
            state["entered_by"] = how
            state["inside_city"] = True
        # Bound replay cost during continuous exploration. Events remain the source of truth.
        if state["event_seq"] % 64 == 0:
            connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                               (run_id, state["event_seq"], json.dumps(state, sort_keys=True)))
    if problem:
        return JSONResponse({"detail": problem[1], "state": state, "accepted": len(accepted)}, status_code=problem[0])
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/explore")
def explore(run_id: str, request: ExploreClock):
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": store.state_at(connection, run, prior_seq), "duplicate": True}
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer exploring")
        if encounter.hostile(state):
            raise HTTPException(409, {"reason": "encounter_active", "state": state})
        sim_time_ms = state["sim_time_ms"] + request.elapsed_ms
        payload = {"sim_time_ms": sim_time_ms, **store.advance_people(state, request.elapsed_ms)}
        store.append(connection, state, "explore", payload, request.request_id, sim_time_ms // 1000)
        state["sim_time_ms"] = sim_time_ms
        state["npcs"] = payload["npcs"]
        store.apply_people(state, payload)
        if state["event_seq"] % 64 == 0:
            connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                               (run_id, state["event_seq"], json.dumps(state, sort_keys=True)))
    return {"state": state, "duplicate": False}


def fight_event(connection, state: dict, journal_before: int, request_id: str, extra: dict) -> None:
    """Record a change made to the fight (state is already changed). Like a round, the event carries the
    resulting fields, so replay needs no rules."""
    payload = {key: state[key] for key in store.FIGHT_FIELDS if key in state}
    payload["journal_added"] = state["journal"][journal_before:]
    payload.update(extra)
    store.append(connection, state, "fight", payload, request_id, state["tick"])


def _punch_target(state: dict, wanted: str | None) -> str | None:
    """Whoever the stranger faces if they're standing; else the nearest attacker (in reach first)."""
    npc = minds.find(state["npcs"], wanted or "")
    if npc is not None and not combat.down(npc):
        return npc["id"]
    here = minds.player_cell(state)
    fighters = [minds.find(state["npcs"], a) for a in (combat.active(state) or {}).get("attackers", [])]
    fighters = [f for f in fighters if f is not None and not combat.down(f)]
    if not fighters:
        return None
    return min(fighters, key=lambda f: minds.math.dist(minds._cell(f), here))["id"]


@router.post("/runs/{run_id}/strike")
def strike(run_id: str, request: Strike):
    """Space in a fight: the stranger's fist (D-41). Code only: lands if they're in reach, fixed damage by armour."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": store.state_at(connection, run, prior_seq), "duplicate": True}
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer interactive")
        if not combat.active(state):
            raise HTTPException(409, {"reason": "no_fight", "message": "You're not fighting anyone."})
        target = _punch_target(state, request.target_id)
        if target is None:
            raise HTTPException(409, {"reason": "no_target", "message": "There's nobody there to hit."})
        journal_before = len(state["journal"])
        result = combat.punch(state, target, state["sim_time_ms"])
        if result["ok"]:  # A punch still recovering is no event: nothing happened.
            fight_event(connection, state, journal_before, request.request_id, {"strike": {"target_id": target, **result}})
    return {"state": state, "duplicate": False, "strike": result}


@router.post("/runs/{run_id}/dev/gate")
def developer_gate(run_id: str, request: GateCommand):
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        if run["mode"] != "developer":
            raise HTTPException(403, "Developer control is unavailable in normal mode")
        prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": store.state_at(connection, run, prior_seq), "duplicate": True}
        store.append(connection, state, "dev_gate", {"open": request.open}, request.request_id, state["tick"])
        state["gate_open"] = request.open
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/dev/fight")
def developer_fight(run_id: str, request: FightCommand):
    """Developer-only: these people come at the stranger now (for testing fights without a model)."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        if run["mode"] != "developer":
            raise HTTPException(403, "Developer control is unavailable in normal mode")
        prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": store.state_at(connection, run, prior_seq), "duplicate": True}
        if any(minds.find(state["npcs"], npc_id) is None for npc_id in request.npc_ids):
            raise HTTPException(422, "Unknown person")
        journal_before = len(state["journal"])
        combat.start(state, request.npc_ids, state["sim_time_ms"], "developer")
        fight_event(connection, state, journal_before, request.request_id, {})
    return {"state": state, "duplicate": False}
