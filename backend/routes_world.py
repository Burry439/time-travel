"""Journeys, walking, the exploration clock, rewinding, and the developer's gate switch."""

from __future__ import annotations

import copy
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import cast
import clock
import combat
import commands
import content
import effects
import encounter
import m2
import paths
import routes_tutorial
import store
import views
from ai import config as ai_config
from ai import decider

router = APIRouter(route_class=views.Shown)  # Replies carry their state's view (views.py).


class NewRun(BaseModel):
    mode: str = "normal"
    scenario: str = "village"  # The level to play (data/content/levels): the village, or a guided one (D-50, D-59).


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
    return {
        "status": "ok",
        "seed_version": store.SEED_VERSION,
        "rules_revision": "D-64",
        "geometry_version": store.GEOMETRY_VERSION,
        "ai": {**ai_config.status(), **decider.status()},
    }


@router.get("/health/ai")
def ai_readiness():
    """An explicit credential/model check; no generation and no world mutation."""
    return ai_config.credential_readiness(ai_config.api_key(), ai_config.judge_model())


@router.post("/runs", status_code=201)
def create_run(request: NewRun):
    if request.mode not in ("normal", "developer"):
        raise HTTPException(422, "Mode must be normal or developer")
    if request.scenario not in content.LEVELS:
        raise HTTPException(422, f"No level called {request.scenario}")
    run_id = uuid4().hex
    with store.lock, store.db() as connection:
        connection.execute(
            "INSERT INTO runs (id,mode,seed_version,geometry_version,scenario,save_format) VALUES (?,?,?,?,?,?)",
            (run_id, request.mode, store.SEED_VERSION, store.GEOMETRY_VERSION, request.scenario, store.SAVE_FORMAT),
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
        rows = connection.execute(
            "SELECT seq,tick,kind,payload,request_id FROM events WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
    return [
        {
            "seq": row["seq"],
            "tick": row["tick"],
            "kind": row["kind"],
            "payload": store.payload_of(row),
            "request_id": row["request_id"],
        }
        for row in rows
    ]


@router.post("/runs/{run_id}/checkpoint")
def checkpoint(run_id: str):
    with store.lock, store.db() as connection:
        _, state = store.load_run(connection, run_id)
        store.save_checkpoint(connection, state)
    return {"event_seq": state["event_seq"], "saved": True}


@router.post("/runs/{run_id}/rewind", status_code=201)
def rewind(run_id: str):
    """Copy this journey up to its last calm moment into a new run, leaving the original untouched."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        point = int(state.get("safe_seq", 0))
        new_id = uuid4().hex
        connection.execute(
            "INSERT INTO runs (id,mode,seed_version,geometry_version,scenario,save_format) VALUES (?,?,?,?,?,?)",
            (new_id, run["mode"], run["seed_version"], run["geometry_version"], run["scenario"], run["save_format"]),
        )
        connection.execute(
            "INSERT INTO events (run_id,seq,tick,kind,payload,request_id,created_at) "
            "SELECT ?,seq,tick,kind,payload,request_id,created_at FROM events WHERE run_id=? AND seq<=?",
            (new_id, run_id, point),
        )
        _, restored = store.load_run(connection, new_id)
    return restored


@router.post("/runs/{run_id}/move")
@commands.answers
def move(run_id: str, request: Move):
    with commands.open(run_id, request) as cmd:
        state = cmd.state
        if encounter.hostile(state):
            raise HTTPException(409, {"reason": "encounter_active", "state": state})
        if stuck := effects.limited(state["player"], "move"):  # Tied up, or the like (D-65).
            raise HTTPException(
                409, {"reason": "cannot_move", "message": f"You can't walk: {stuck['name']}.", "state": state}
            )
        cells = request.cells or ([[request.x, request.y]] if request.x is not None and request.y is not None else [])
        if not cells or any(len(cell) != 2 for cell in cells):
            raise HTTPException(422, "Send x and y, or a list of [x, y] cells")

        # Open because its bar was lifted off (not the captain's word, not the developer switch): a guard in the gap.
        holder = combat.gate_held_by(state) if state["gate_open"] and not m2.gate_barred(state) else None

        blocked = paths.grid(state)  # Felled trees no longer block.
        gate, (width, height) = paths.gate(state), content.map_of(state)["size"]

        def passable(x: int, y: int) -> bool:
            if not (0 <= x < width and 0 <= y < height):
                return False
            if paths.in_wall(gate, (x, y)):
                through_gate = paths.in_gap(gate, (x, y)) and state["gate_open"] and holder is None
                return through_gate or paths.breached(state, (x, y))
            return (x, y) not in blocked

        # Walk the cells in order; stop at the first illegal step, keeping the legal ones before it.
        x, y = state["player"]["x"], state["player"]["y"]
        accepted: list[list[int]] = []
        problem = None
        for nx, ny in cells:
            dx, dy = nx - x, ny - y
            if max(abs(dx), abs(dy)) != 1:
                problem = (422, "Move must cross exactly one adjacent cell")
            elif not passable(nx, ny):
                problem = (
                    403,
                    f"{holder['name']} steps into the gateway and bars your way."
                    if holder and paths.in_wall(gate, (nx, ny)) and paths.in_gap(gate, (nx, ny))
                    else "A building, city wall, or closed gate blocks the path",
                )
            elif dx and dy and (not passable(x + dx, y) or not passable(x, y + dy)):
                problem = (403, "Cannot cut diagonally through a blocked corner")
            if problem:
                break
            x, y = nx, ny
            accepted.append([x, y])
            if paths.arrived(state, (x, y)):
                break  # Inside the city.
        if not accepted:
            raise HTTPException(*problem)
        tick = state["sim_time_ms"] // 1000  # Walking takes no clock time: the exploration clock runs alongside.
        if encounter.active(state):  # A conversation doesn't follow the stranger: walking off ends it for them.
            moved = copy.deepcopy(state)
            moved["player"].update(x=x, y=y)
            encounter.prune(moved)
            if moved.get("encounter") != state.get("encounter"):
                state.update(
                    encounter=moved.get("encounter"), npcs=moved["npcs"], pending_minds=moved.get("pending_minds", [])
                )
        state["player"].update(x=x, y=y)
        cmd.save("move", tick, {"running": request.running, "path": accepted})
        if paths.arrived(state, (x, y)) and not state["inside_city"]:
            state["entered_by"] = (
                "admitted" if state.get("admitted") else "unbarred" if state.get("gate_unbarred_by") else "other"
            )
            state["inside_city"] = True
            cmd.save("objective_complete", tick)
            routes_tutorial.progress(cmd)  # A level that asked to get inside is told its end (D-59).
    if problem:
        body = views.shown(
            {"detail": problem[1], "state": state, "accepted": len(accepted)}
        )  # Built by hand: shown here.
        return JSONResponse(body, status_code=problem[0])
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/explore")
@commands.answers
def explore(run_id: str, request: ExploreClock):
    with commands.open(run_id, request) as cmd:
        state = cmd.state
        if encounter.hostile(state):
            raise HTTPException(409, {"reason": "encounter_active", "state": state})
        sim_time_ms = state["sim_time_ms"] + request.elapsed_ms
        people = clock.advance_people(state, request.elapsed_ms)
        state["sim_time_ms"] = sim_time_ms
        state["npcs"] = people["npcs"]
        store.apply_people(state, people)
        cmd.save("explore", sim_time_ms // 1000)
        routes_tutorial.progress(cmd)  # The tutorial moves on with the clock, too (D-50).
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/dev/gate")
@commands.answers
def developer_gate(run_id: str, request: GateCommand):
    with commands.open(run_id, request, developer=True, playable=False) as cmd:
        cmd.state["gate_open"] = request.open
        cmd.save("dev_gate", cmd.state["tick"])
    return {"state": cmd.state, "duplicate": False}


@router.post("/runs/{run_id}/dev/fight")
@commands.answers
def developer_fight(run_id: str, request: FightCommand):
    """Developer-only: these people come at the stranger now (for testing fights without a model)."""
    with commands.open(run_id, request, developer=True, playable=False) as cmd:
        if any(cast.find(cmd.state["npcs"], npc_id) is None for npc_id in request.npc_ids):
            raise HTTPException(422, "Unknown person")
        combat.start(cmd.state, request.npc_ids, cmd.state["sim_time_ms"], "developer")
        cmd.save("fight", cmd.state["tick"])
    return {"state": cmd.state, "duplicate": False}
