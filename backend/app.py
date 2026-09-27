"""Milestone 0 authoritative movement and append-only save/replay service."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import copy
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import m2
import npc_sim

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "demo.sqlite3"))
WORLD_GEOMETRY = json.loads((ROOT / "data" / "world_geometry.json").read_text())
WORLD_GEOMETRY_V2 = json.loads((ROOT / "data" / "world_geometry_v2.json").read_text())
GEOMETRY_VERSION = WORLD_GEOMETRY["version"]
SEED_VERSION = 3
MOVE_SPEED_CELLS_PER_SECOND = 7.1875
RUN_SPEED_CELLS_PER_SECOND = 11.5
NPCS = [
    {"id": "npc_roderic_vale", "name": "Roderic", "role": "Gate captain", "x": 48, "y": 11},
    {"id": "npc_bren_marr", "name": "Bren", "role": "Gate guard", "x": 44, "y": 14},
    {"id": "npc_oren_dast", "name": "Oren", "role": "Gate guard", "x": 52, "y": 14},
    {"id": "npc_hessa_marr", "name": "Hessa", "role": "Innkeeper", "x": 34, "y": 51},
    {"id": "npc_mara_venn", "name": "Mara", "role": "Blacksmith", "x": 18, "y": 25},
    {"id": "npc_jory_venn", "name": "Jory", "role": "Smith apprentice", "x": 21, "y": 28},
    {"id": "npc_tomas_reed", "name": "Tomas", "role": "Carpenter", "x": 64, "y": 26},
    {"id": "npc_darin_ko", "name": "Darin", "role": "Merchant", "x": 80, "y": 30},
]
PATROL_GUARDS = [
    {"id": "npc_elin_west", "name": "Elin", "role": "Watch scout", "x": 47, "y": 23},
    {"id": "npc_kade_east", "name": "Kade", "role": "Patrol guard", "x": 52, "y": 35},
]

app = FastAPI(title="Time Travel RPG Milestone 2", version="0.2.0")
_lock = threading.RLock()


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL CHECK(mode IN ('normal','developer')),
                seed_version INTEGER NOT NULL,
                geometry_version INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL REFERENCES runs(id),
                seq INTEGER NOT NULL,
                tick INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                request_id TEXT,
                PRIMARY KEY(run_id, seq),
                UNIQUE(run_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS action_requests (
                run_id TEXT NOT NULL REFERENCES runs(id),
                request_id TEXT NOT NULL,
                final_seq INTEGER NOT NULL,
                request_json TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(run_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                run_id TEXT NOT NULL REFERENCES runs(id),
                seq INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                PRIMARY KEY(run_id, seq)
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(action_requests)")}
        if "request_json" not in columns:
            connection.execute("ALTER TABLE action_requests ADD COLUMN request_json TEXT NOT NULL DEFAULT ''")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initial_state(run: sqlite3.Row) -> dict:
    state = {
        "run_id": run["id"], "mode": run["mode"], "seed_version": run["seed_version"],
        "geometry_version": run["geometry_version"], "event_seq": 0, "tick": 0,
        "sim_time_ms": 0,
        "player": {"x": 48, "y": 68, "alive": True},
        "gate_open": False, "inside_city": False, "objective": "Get inside the city",
        "npcs": npc_sim.seed_npcs(NPCS + PATROL_GUARDS, WORLD_GEOMETRY)
        if run["seed_version"] >= 3 else copy.deepcopy(NPCS),
    }
    if run["seed_version"] >= 2:
        state.update(m2.seed_m2())
    else:
        state.update({"objects": {}, "agreements": {}, "journal": [],
                      "water_spilled_l": 0.0, "last_action": None})
    return state


def reduce_event(state: dict, event: sqlite3.Row) -> None:
    payload = json.loads(event["payload"])
    if event["kind"] == "move":
        state["player"].update(x=payload["x"], y=payload["y"])
        state["sim_time_ms"] = payload["sim_time_ms"]
    elif event["kind"] == "explore":
        state["sim_time_ms"] = payload["sim_time_ms"]
        state["npcs"] = payload["npcs"]
    elif event["kind"] == "dev_gate":
        state["gate_open"] = payload["open"]
    elif event["kind"] == "objective_complete":
        state["inside_city"] = True
    elif event["kind"] == "physical_action":
        state["objects"] = payload["objects"]
        state["agreements"] = payload["agreements"]
        state["water_spilled_l"] = payload["water_spilled_l"]
        state["journal"].append(payload["journal_entry"])
        state["last_action"] = payload["journal_entry"]
        state["sim_time_ms"] = payload["sim_time_ms"]
        if "npcs" in payload:
            state["npcs"] = payload["npcs"]
    else:
        raise ValueError(f"Unknown event kind {event['kind']}")
    state["event_seq"] = event["seq"]
    state["tick"] = event["tick"]


def load_run(connection: sqlite3.Connection, run_id: str) -> tuple[sqlite3.Row, dict]:
    run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404, "Run not found")
    checkpoint = connection.execute("SELECT seq,state_json FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1",
                                    (run_id,)).fetchone()
    state = json.loads(checkpoint["state_json"]) if checkpoint else initial_state(run)
    for event in connection.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq",
                                    (run_id, state["event_seq"])):
        reduce_event(state, event)
    return run, state


def state_at(connection: sqlite3.Connection, run: sqlite3.Row, sequence: int) -> dict:
    """Reconstruct the exact saved result for an idempotent retry."""
    checkpoint = connection.execute("SELECT seq,state_json FROM checkpoints WHERE run_id=? AND seq<=? ORDER BY seq DESC LIMIT 1",
                                    (run["id"], sequence)).fetchone()
    state = json.loads(checkpoint["state_json"]) if checkpoint else initial_state(run)
    for event in connection.execute(
        "SELECT * FROM events WHERE run_id=? AND seq>? AND seq<=? ORDER BY seq",
        (run["id"], state["event_seq"], sequence)
    ):
        reduce_event(state, event)
    return state


def append(connection: sqlite3.Connection, state: dict, kind: str, payload: dict, request_id: str,
           tick: int) -> None:
    sequence = state["event_seq"] + 1
    connection.execute(
        "INSERT INTO events (run_id, seq, tick, kind, payload, request_id) VALUES (?,?,?,?,?,?)",
        (state["run_id"], sequence, tick, kind, json.dumps(payload, sort_keys=True), request_id),
    )
    state["event_seq"] = sequence
    state["tick"] = tick


class NewRun(BaseModel):
    mode: str = "normal"


class Move(BaseModel):
    x: int = Field(ge=0, le=95)
    y: int = Field(ge=0, le=71)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)
    running: bool = False


class ExploreClock(BaseModel):
    elapsed_ms: int = Field(ge=1, le=1000)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class GateCommand(BaseModel):
    open: bool
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class PhysicalAction(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(min_length=1, max_length=500)
    selected_ids: list[str] = Field(default_factory=list, max_length=8)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


def check_request(connection: sqlite3.Connection, state: dict, expected_version: int,
                  request_id: str) -> int | None:
    prior = connection.execute(
        "SELECT seq FROM events WHERE run_id=? AND request_id=?", (state["run_id"], request_id)
    ).fetchone()
    if prior:
        return int(prior["seq"])
    if expected_version != state["event_seq"]:
        raise HTTPException(409, {"reason": "stale_state", "state": state})
    return None


@app.get("/health")
def health():
    with db() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "seed_version": SEED_VERSION, "geometry_version": GEOMETRY_VERSION}


@app.post("/runs", status_code=201)
def create_run(request: NewRun):
    if request.mode not in ("normal", "developer"):
        raise HTTPException(422, "Mode must be normal or developer")
    run_id = uuid4().hex
    with _lock, db() as connection:
        connection.execute(
            "INSERT INTO runs (id,mode,seed_version,geometry_version) VALUES (?,?,?,?)",
            (run_id, request.mode, SEED_VERSION, GEOMETRY_VERSION),
        )
        _, state = load_run(connection, run_id)
    return state


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    with db() as connection:
        _, state = load_run(connection, run_id)
    return state


@app.get("/runs/{run_id}/events")
def get_events(run_id: str):
    with db() as connection:
        load_run(connection, run_id)
        rows = connection.execute("SELECT seq,tick,kind,payload,request_id FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
    return [{"seq": row["seq"], "tick": row["tick"], "kind": row["kind"],
             "payload": json.loads(row["payload"]), "request_id": row["request_id"]} for row in rows]


@app.get("/runs/{run_id}/nearby")
def get_nearby(run_id: str):
    with db() as connection:
        _, state = load_run(connection, run_id)
    return {"objects": m2.nearby(state),
            "npcs": [n for n in state["npcs"] if m2.npc_near(state, n["id"])],
            "event_seq": state["event_seq"]}


@app.post("/runs/{run_id}/checkpoint")
def checkpoint(run_id: str):
    with _lock, db() as connection:
        _, state = load_run(connection, run_id)
        connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                           (run_id, state["event_seq"], json.dumps(state, sort_keys=True)))
    return {"event_seq": state["event_seq"], "saved": True}


@app.post("/runs/{run_id}/actions")
def physical_action(run_id: str, request: PhysicalAction):
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        request_json = json.dumps({"text": request.text, "selected_ids": request.selected_ids}, sort_keys=True)
        prior = connection.execute("SELECT final_seq,request_json FROM action_requests WHERE run_id=? AND request_id=?",
                                   (run_id, request.request_id)).fetchone()
        if prior:
            if prior["request_json"] and prior["request_json"] != request_json:
                raise HTTPException(409, {"reason": "request_id_conflict"})
            return {"state": state_at(connection, run, prior["final_seq"]), "duplicate": True}
        event_collision = connection.execute("SELECT 1 FROM events WHERE run_id=? AND request_id=?",
                                             (run_id, request.request_id)).fetchone()
        if event_collision:
            raise HTTPException(409, {"reason": "request_id_conflict"})
        if request.expected_version != state["event_seq"]:
            raise HTTPException(409, {"reason": "stale_state", "state": state})
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer interactive")
        if run["seed_version"] < 2:
            raise HTTPException(409, "This run uses an earlier world seed. Start a new run for Milestone 2.")
        if len(set(request.selected_ids)) != len(request.selected_ids):
            raise HTTPException(422, "Selected entity IDs must be unique")
        plan, parse_error = m2.parse(request.text, request.selected_ids, state)
        if parse_error:
            plan = [{"step_id": "step_1", "operation_key": "parse", "actor_id": "player",
                     "input_refs": [], "output_bindings": [], "depends_on": [],
                     "required_capabilities": [], "required_skill": None,
                     "effort_seconds": 0, "risk_tags": [], "status": "pending"}]
        for index, step in enumerate(plan):
            draft = copy.deepcopy(state)
            category, reason = (("unsupported" if parse_error.startswith("Unsupported step") else "needs_clarification"),
                                parse_error) if parse_error else m2.apply_step(draft, step)
            step["status"] = "completed" if category == "success" else category
            effort_ms = step["effort_seconds"] * 1000 if category == "success" else 0
            sim_time_ms = state["sim_time_ms"] + effort_ms
            entry = {"text": request.text, "step": step, "category": category,
                     "player_cell": [state["player"]["x"], state["player"]["y"]],
                     "reason": reason, "event_id": state["event_seq"] + 1}
            payload = {"objects": draft["objects"] if category == "success" else state["objects"],
                       "agreements": draft["agreements"] if category == "success" else state["agreements"],
                       "water_spilled_l": draft["water_spilled_l"] if category == "success" else state["water_spilled_l"],
                       "journal_entry": entry, "sim_time_ms": sim_time_ms}
            if run["seed_version"] >= 3:
                payload["npcs"] = npc_sim.advance_npcs(state["npcs"], effort_ms,
                                                        state["sim_time_ms"], WORLD_GEOMETRY)
            append(connection, state, "physical_action", payload,
                   request.request_id if index == 0 else f"{request.request_id}:step:{index + 1}",
                   sim_time_ms // 1000)
            state["objects"] = payload["objects"]
            state["agreements"] = payload["agreements"]
            state["water_spilled_l"] = payload["water_spilled_l"]
            state["journal"].append(entry)
            state["last_action"] = entry
            state["sim_time_ms"] = sim_time_ms
            if "npcs" in payload:
                state["npcs"] = payload["npcs"]
            if category != "success":
                break
        connection.execute("INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?)",
                           (run_id, request.request_id, state["event_seq"], request_json))
    return {"state": state, "duplicate": False}


@app.post("/runs/{run_id}/move")
def move(run_id: str, request: Move):
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        prior_seq = check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            objective = connection.execute(
                "SELECT seq FROM events WHERE run_id=? AND request_id=?",
                (run_id, f"objective:{request.request_id}"),
            ).fetchone()
            end_seq = int(objective["seq"]) if objective else prior_seq
            return {"state": state_at(connection, run, end_seq), "duplicate": True}
        old_x, old_y = state["player"]["x"], state["player"]["y"]
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer movable")
        dx, dy = request.x - old_x, request.y - old_y
        if max(abs(dx), abs(dy)) != 1:
            raise HTTPException(422, "Move must cross exactly one adjacent cell")

        def passable(x: int, y: int) -> bool:
            if not (0 <= x <= 95 and 0 <= y <= 71):
                return False
            if 4 <= y <= 8:
                return 46 <= x <= 50 and state["gate_open"]
            if state["geometry_version"] >= 2:
                geometry = WORLD_GEOMETRY_V2 if state["geometry_version"] == 2 else WORLD_GEOMETRY
                for building in geometry["buildings"] + geometry["obstacles"]:
                    bx, by, width, height = building["cells"]
                    if bx <= x < bx + width and by <= y < by + height:
                        return False
            return True

        if not passable(request.x, request.y):
            raise HTTPException(403, "A building, city wall, or closed gate blocks the path")
        if dx and dy and (not passable(old_x + dx, old_y) or not passable(old_x, old_y + dy)):
            raise HTTPException(403, "Cannot cut diagonally through a blocked corner")
        speed = RUN_SPEED_CELLS_PER_SECOND if request.running else MOVE_SPEED_CELLS_PER_SECOND
        travel_ms = round(1000 * math.hypot(dx, dy) / speed) if run["seed_version"] < 3 else 0
        sim_time_ms = state["sim_time_ms"] + travel_ms  # New runs use the exploration clock instead.
        tick = sim_time_ms // 1000  # One simulation tick is one second.
        append(connection, state, "move", {"x": request.x, "y": request.y,
                                           "running": request.running,
                                           "sim_time_ms": sim_time_ms}, request.request_id, tick)
        state["sim_time_ms"] = sim_time_ms
        state["player"].update(x=request.x, y=request.y)
        if request.y <= 3 and not state["inside_city"]:
            append(connection, state, "objective_complete", {"location": "loc_city_interior"},
                   f"objective:{request.request_id}", tick)
            state["inside_city"] = True
        # Bound replay cost during continuous exploration. Events remain the source of truth.
        if state["event_seq"] % 64 == 0:
            connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                               (run_id, state["event_seq"], json.dumps(state, sort_keys=True)))
    return {"state": state, "duplicate": False}


@app.post("/runs/{run_id}/explore")
def explore(run_id: str, request: ExploreClock):
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        if run["seed_version"] < 3:
            raise HTTPException(409, "This journey uses movement-based time")
        prior_seq = check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": state_at(connection, run, prior_seq), "duplicate": True}
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer exploring")
        sim_time_ms = state["sim_time_ms"] + request.elapsed_ms
        npcs = npc_sim.advance_npcs(state["npcs"], request.elapsed_ms,
                                    state["sim_time_ms"], WORLD_GEOMETRY)
        append(connection, state, "explore", {"sim_time_ms": sim_time_ms, "npcs": npcs},
               request.request_id, sim_time_ms // 1000)
        state["sim_time_ms"] = sim_time_ms
        state["npcs"] = npcs
        if state["event_seq"] % 64 == 0:
            connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                               (run_id, state["event_seq"], json.dumps(state, sort_keys=True)))
    return {"state": state, "duplicate": False}


@app.post("/runs/{run_id}/dev/gate")
def developer_gate(run_id: str, request: GateCommand):
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        if run["mode"] != "developer":
            raise HTTPException(403, "Developer control is unavailable in normal mode")
        prior_seq = check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": state_at(connection, run, prior_seq), "duplicate": True}
        append(connection, state, "dev_gate", {"open": request.open}, request.request_id, state["tick"])
        state["gate_open"] = request.open
    return {"state": state, "duplicate": False}
