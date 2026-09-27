"""Milestone 0 authoritative movement and append-only save/replay service."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from typing import Literal

from pydantic import BaseModel, Field
import crafting
import encounter
import m2
import minds
import npc_sim
import talk
from ai import config as ai_config, decider, illustrator, judge, telemetry, voice

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "demo.sqlite3"))
ASSET_DIR = ROOT / "data" / "assets"
WORLD_GEOMETRY = json.loads((ROOT / "data" / "world_geometry.json").read_text())
WORLD_GEOMETRY_V2 = json.loads((ROOT / "data" / "world_geometry_v2.json").read_text())
GEOMETRY_VERSION = WORLD_GEOMETRY["version"]
# 4 adds loose road materials and material data for crafting; 5 adds materials across the map,
# fellable trees and saplings, and NPC health; 6 adds people's own stock (Darin's lodestone, Mara's
# needles, Hessa's bowls) and the gate trough; 7 adds the gate beam and its brackets, and Tomas's rope,
# ladder and fulcrum stone.
SEED_VERSION = 7
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
            CREATE TABLE IF NOT EXISTS craft_traces (
                run_id TEXT NOT NULL REFERENCES runs(id),
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                trace_json TEXT NOT NULL,
                PRIMARY KEY(run_id, request_id)
            );
            -- Sprites are presentation, not physics: kept outside the event log.
            CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id),
                object_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','ready','failed','disabled')),
                record_json TEXT NOT NULL,
                trace_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS mind_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event_seq INTEGER NOT NULL,
                npc_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                trace_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                role TEXT NOT NULL,
                model TEXT,
                prompt_version TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 1,
                ok INTEGER NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        state.update(m2.seed_m2(run["seed_version"]))
    else:
        state.update({"objects": {}, "agreements": {}, "journal": [],
                      "water_spilled_l": 0.0, "last_action": None})
    if run["seed_version"] >= 5:
        for npc in state["npcs"]:
            npc.update(alive=True, health=100, injuries=[])
    return state


# Events the player causes. A request is stale only if the client hasn't seen the latest of
# these; people thinking or the clock ticking in between never makes the player's request stale.
PLAYER_KINDS = {"move", "physical_action", "craft", "talk", "round", "dev_gate", "objective_complete"}


def _is_stale(state: dict, expected_version: int) -> bool:
    return not state.get("player_seq", 0) <= expected_version <= state["event_seq"]


def reduce_event(state: dict, event: sqlite3.Row) -> None:
    payload = json.loads(event["payload"])
    if event["kind"] in PLAYER_KINDS:
        state["player_seq"] = event["seq"]
    if event["kind"] == "move":
        state["player"].update(x=payload["x"], y=payload["y"])
        state["sim_time_ms"] = payload["sim_time_ms"]
        if "encounter" in payload:  # Walked away from a conversation.
            state.update(encounter=payload["encounter"], npcs=payload["npcs"], pending_minds=payload["pending_minds"])
    elif event["kind"] == "explore":
        state["sim_time_ms"] = payload["sim_time_ms"]
        state["npcs"] = payload["npcs"]
        _apply_people(state, payload)
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
        _apply_people(state, payload)
    elif event["kind"] == "craft":
        crafting.apply_payload(state, payload)
        _apply_people(state, payload)
    elif event["kind"] == "round":
        _apply_round(state, payload)
    elif event["kind"] == "talk":
        talk.apply_payload(state, payload)
        _apply_people(state, payload)
    elif event["kind"] == "minds":
        state["npcs"] = payload["npcs"]
        state["player"] = payload["player"]
        _apply_people(state, payload)
    else:
        raise ValueError(f"Unknown event kind {event['kind']}")
    state["event_seq"] = event["seq"]
    state["tick"] = event["tick"]


def _apply_people(state: dict, payload: dict) -> None:
    """Fields shared by events in which people act: their pending thoughts, what the player heard,
    and the latest calm moment to rewind to."""
    if "pending_minds" in payload:
        state["pending_minds"] = payload["pending_minds"]
    if "player" in payload:
        state["player"] = payload["player"]  # e.g. struck by someone during this time
    state["journal"].extend(payload.get("people_journal", []))
    if "safe_seq" in payload:
        state["safe_seq"] = payload["safe_seq"]
    if "encounter" in payload:
        state["encounter"] = payload["encounter"]


# A round changes many things at once (anything a Try Something can, a reply, people moving on),
# so its event carries the resulting fields rather than deltas.
ROUND_FIELDS = ("objects", "npcs", "player", "encounter", "pending_minds", "agreements", "sim_time_ms",
                "water_spilled_l", "last_action", "gate_open", "barred_until", "trades")


def _round_payload(before: dict, after: dict, record: dict) -> dict:
    payload = {key: after.get(key) for key in ROUND_FIELDS}
    payload["trades"] = after.get("trades") or {}
    payload["journal_added"] = after["journal"][len(before["journal"]):]
    payload["learned_added"] = after.get("learned", [])[len(before.get("learned", [])):]
    if after.get("admitted") and not before.get("admitted"):
        payload["admitted"] = after["admitted"]
    payload["round"] = {key: record.get(key) for key in (
        "round", "entries", "ended", "walked_away", "replier", "effort_seconds", "walk", "arrested")}
    payload["round"]["did"] = {npc_id: intent["action"] for npc_id, intent in (record.get("intents") or {}).items()}
    return payload


def _apply_round(state: dict, payload: dict) -> None:
    for key in ROUND_FIELDS:
        state[key] = payload[key]
    state["journal"].extend(payload["journal_added"])
    state.setdefault("learned", []).extend(payload["learned_added"])
    if payload.get("admitted"):
        state["admitted"] = payload["admitted"]
    if "safe_seq" in payload:
        state["safe_seq"] = payload["safe_seq"]
    state["last_round"] = payload["round"]


def _advance_people(state: dict, elapsed_ms: int) -> dict:
    """Payload fields for time passing: routines, and jobs people chose (seed 5+)."""
    if state["seed_version"] < 5:
        return {"npcs": npc_sim.advance_npcs(state["npcs"], elapsed_ms, state["sim_time_ms"], WORLD_GEOMETRY)}
    probe = dict(state)
    probe["pending_minds"] = list(state.get("pending_minds", []))
    npcs, heard, player = minds.advance_world(probe, elapsed_ms, state["sim_time_ms"])
    return {"npcs": npcs, "player": player, "pending_minds": probe["pending_minds"], "people_journal": heard,
            "encounter": probe.get("encounter")}


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
    if kind in PLAYER_KINDS:
        state["player_seq"] = sequence
    state["tick"] = tick


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


class CraftRequest(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(min_length=1, max_length=600)
    selected_ids: list[str] = Field(default_factory=list, max_length=12)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


def check_request(connection: sqlite3.Connection, state: dict, expected_version: int,
                  request_id: str) -> int | None:
    prior = connection.execute(
        "SELECT seq FROM events WHERE run_id=? AND request_id=?", (state["run_id"], request_id)
    ).fetchone()
    if prior:
        return int(prior["seq"])
    if _is_stale(state, expected_version):
        raise HTTPException(409, {"reason": "stale_state", "state": state})
    return None


@app.get("/health")
def health():
    with db() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok", "seed_version": SEED_VERSION, "geometry_version": GEOMETRY_VERSION,
            "ai": {**ai_config.status(), **decider.status()}}


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
        if _is_stale(state, request.expected_version):
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
                payload.update(_advance_people(state, effort_ms))
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
            _apply_people(state, payload)
            if category != "success":
                break
        connection.execute("INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?)",
                           (run_id, request.request_id, state["event_seq"], request_json))
    return {"state": state, "duplicate": False}


_crafting_runs: set[str] = set()
_asset_jobs: set[str] = set()
_asset_jobs_lock = threading.Lock()
ASSET_ID = re.compile(r"^spr_[0-9a-f]{8}_[a-z0-9_]+$")


def _service_message(judged: judge.JudgeCall) -> str | None:
    if judged.status == "disabled":
        return "AI crafting isn't set up on this computer yet. Add OPENAI_API_KEY to backend/.env and restart the backend."
    if judged.status == "capped":
        return "This journey has used its allowance of AI calls, so nothing was judged. Nothing changed."
    if judged.status == "error":
        return "The judge couldn't be reached, so nothing was decided and nothing changed."
    return None


def _craft_response(run: sqlite3.Row, state: dict, trace: dict | None, duplicate: bool) -> dict:
    response = {"state": state, "duplicate": duplicate}
    if run["mode"] == "developer":
        response["trace"] = trace
    return response


def _load_trace(connection: sqlite3.Connection, run_id: str, request_id: str) -> dict | None:
    row = connection.execute("SELECT trace_json FROM craft_traces WHERE run_id=? AND request_id=?",
                             (run_id, request_id)).fetchone()
    return json.loads(row["trace_json"]) if row else None


@app.post("/runs/{run_id}/craft")
def craft(run_id: str, request: CraftRequest, background: BackgroundTasks):
    """Judge a making attempt outside the lock, then revalidate and commit one event."""
    request_json = json.dumps({"text": request.text, "selected_ids": request.selected_ids}, sort_keys=True)
    with db() as connection:
        _, peek = load_run(connection, run_id)
    if encounter.active(peek):  # Face to face with someone: this is the stranger's part of a round.
        return _play_round(run_id, EncounterAct(kind="do", text=request.text, selected_ids=request.selected_ids,
                                                expected_version=request.expected_version,
                                                request_id=request.request_id), background)
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        prior = connection.execute("SELECT final_seq,request_json FROM action_requests WHERE run_id=? AND request_id=?",
                                   (run_id, request.request_id)).fetchone()
        if prior:
            if prior["request_json"] != request_json:
                raise HTTPException(409, {"reason": "request_id_conflict"})
            return _craft_response(run, state_at(connection, run, prior["final_seq"]),
                                   _load_trace(connection, run_id, request.request_id), duplicate=True)
        if connection.execute("SELECT 1 FROM events WHERE run_id=? AND request_id=?",
                              (run_id, request.request_id)).fetchone():
            raise HTTPException(409, {"reason": "request_id_conflict"})
        if _is_stale(state, request.expected_version):
            raise HTTPException(409, {"reason": "stale_state", "state": state})
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer interactive")
        if run["seed_version"] < 4:
            raise HTTPException(409, "This journey began before crafting existed. Start a new journey to make things.")
        if run_id in _crafting_runs:
            raise HTTPException(409, {"reason": "in_progress"})
        _crafting_runs.add(run_id)
        context = crafting.build_context(state, request.text, request.selected_ids)
        calls_used = telemetry.calls_for_run(connection, run_id)
    try:
        # The model call happens outside the lock and outside any transaction.
        if calls_used >= ai_config.max_calls_per_run():
            judged = judge.JudgeCall(status="capped", error=f"Reached MAX_MODEL_CALLS_PER_RUN ({calls_used}).")
        else:
            judged = judge.judge_craft(context)
        with _lock, db() as connection:
            run, state = load_run(connection, run_id)
            if judged.attempts:
                telemetry.record(connection, run_id, "judge", judged.model, judged.prompt_version, judged.latency_ms,
                                 judged.status == "ok", judged.error, judged.input_tokens, judged.output_tokens,
                                 judged.attempts)
            # Validation runs against the state as it is now, not the snapshot the judge saw,
            # one step at a time, stopping at the first step that does not succeed.
            payload, verdict, after = crafting.resolve_attempt(
                state, run_id, request.text, judged.result, _service_message(judged), request.request_id,
                state["sim_time_ms"])
            if run["seed_version"] >= 5:
                payload["perceptions"] = minds.perceive(after, payload["journal_entry"])
                minds.apply_perceptions(after, payload["perceptions"])
                payload["safe_seq"] = state["event_seq"] if minds.calm(state) else state.get("safe_seq", 0)
            payload.update(_advance_people(after, verdict["effort_seconds"] * 1000))
            append(connection, state, "craft", payload, request.request_id, payload["sim_time_ms"] // 1000)
            crafting.apply_payload(state, payload)
            _apply_people(state, payload)
            connection.execute("INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?)",
                               (run_id, request.request_id, state["event_seq"], request_json))
            new_objects = [obj for step in payload["steps"] for obj in step["new_objects"]]
            trace = _record_attempt(connection, run_id, request.request_id, state["event_seq"], request.text,
                                    request.selected_ids, context, judged, verdict, new_objects, background)
    finally:
        _crafting_runs.discard(run_id)
    return _craft_response(run, state, trace, duplicate=False)


def _record_attempt(connection: sqlite3.Connection, run_id: str, request_id: str, event_seq: int, text: str,
                    selected_ids: list[str], context: dict, judged: judge.JudgeCall, verdict: dict,
                    new_objects: list[dict], background: BackgroundTasks) -> dict:
    """The developer trace for one Try Something, and a painting queued for each new sprite."""
    trace = {"request_id": request_id, "event_seq": event_seq, "text": text, "selected_ids": selected_ids,
             "context": context, "judge": judged.as_dict(),
             "validator": {key: verdict[key] for key in (
                 "category", "action", "reason", "effort_seconds", "notes", "consumed_ids", "tool_ids",
                 "new_spec", "take_ids", "transform", "harm", "fill", "demonstration", "give", "property", "steps")},
             "made": new_objects[0]["id"] if new_objects else None, "made_ids": [o["id"] for o in new_objects]}
    connection.execute("INSERT INTO craft_traces (run_id,request_id,trace_json) VALUES (?,?,?)",
                       (run_id, request_id, json.dumps(trace)))
    # One painting per distinct sprite; identical transform pieces share one.
    for asset_id, obj in {o["sprite_asset_id"]: o for o in reversed(new_objects)}.items():
        record = {key: obj[key] for key in ("id", "name", "description", "materials")}
        connection.execute("INSERT INTO assets (asset_id,run_id,object_id,status,record_json) VALUES (?,?,?,'pending',?)",
                           (asset_id, run_id, obj["id"], json.dumps(record)))
        background.add_task(_generate_asset, asset_id)
    return trace


def _judge(context: dict, calls_used: int) -> judge.JudgeCall:
    if calls_used >= ai_config.max_calls_per_run():
        return judge.JudgeCall(status="capped", error=f"Reached MAX_MODEL_CALLS_PER_RUN ({calls_used}).")
    return judge.judge_craft(context)


def _generate_asset(asset_id: str) -> None:
    """Paint one sprite. Runs after the response; failure leaves the placeholder in play."""
    with _asset_jobs_lock:
        if asset_id in _asset_jobs:
            return
        _asset_jobs.add(asset_id)
    try:
        with db() as connection:
            row = connection.execute("SELECT run_id,record_json FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None:
            return
        try:
            call = illustrator.generate_sprite(json.loads(row["record_json"]), ASSET_DIR / f"{asset_id}.png")
        except Exception as error:  # Never leave a job silently pending (it would be re-queued forever).
            call = illustrator.SpriteCall(status="failed", error=f"{type(error).__name__}: {error}")
        with _lock, db() as connection:
            connection.execute("UPDATE assets SET status=?,trace_json=?,updated_at=CURRENT_TIMESTAMP WHERE asset_id=?",
                               (call.status, json.dumps(call.as_dict()), asset_id))
            if call.model:
                telemetry.record(connection, row["run_id"], "illustrator", call.model, call.prompt_version,
                                 call.latency_ms, call.status == "ready", call.error)
    finally:
        with _asset_jobs_lock:
            _asset_jobs.discard(asset_id)


@app.get("/assets/{asset_id}")
def get_asset(asset_id: str, background: BackgroundTasks):
    """200 PNG when painted, 202 while painting, 404 with a status when there is no picture."""
    if not ASSET_ID.match(asset_id):
        raise HTTPException(404, "Unknown asset")
    with db() as connection:
        row = connection.execute("SELECT status,trace_json FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Unknown asset")
        status = row["status"]
        path = ASSET_DIR / f"{asset_id}.png"
        if status == "ready" and path.exists():
            return FileResponse(path, media_type="image/png")
        if status == "disabled" and ai_config.images_enabled():
            connection.execute("UPDATE assets SET status='pending' WHERE asset_id=?", (asset_id,))
            status = "pending"
    if status == "pending":
        with _asset_jobs_lock:
            running = asset_id in _asset_jobs
        if not running:  # e.g. the backend restarted while painting
            background.add_task(_generate_asset, asset_id)
        return JSONResponse({"status": "pending"}, status_code=202)
    return JSONResponse({"status": status, "error": json.loads(row["trace_json"]).get("error")}, status_code=404)


def _developer_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404, "Run not found")
    if run["mode"] != "developer":
        raise HTTPException(403, "AI traces are available in developer playtests only")
    return run


@app.get("/runs/{run_id}/traces")
def get_traces(run_id: str, limit: int = 10):
    """Developer view of recent judge calls, validator decisions, sprites, and model telemetry."""
    with db() as connection:
        _developer_run(connection, run_id)
        rows = connection.execute("SELECT trace_json FROM craft_traces WHERE run_id=? ORDER BY rowid DESC LIMIT ?",
                                  (run_id, max(1, min(limit, 50)))).fetchall()
        assets = connection.execute("SELECT asset_id,object_id,status,record_json,trace_json,updated_at FROM assets "
                                    "WHERE run_id=? ORDER BY rowid DESC LIMIT 20", (run_id,)).fetchall()
        calls = telemetry.recent(connection, run_id)
        thoughts = connection.execute("SELECT trace_json FROM mind_traces WHERE run_id=? ORDER BY id DESC LIMIT 20",
                                      (run_id,)).fetchall()
    return {"ai": {**ai_config.status(), **decider.status()}, "judge_prompt_version": judge.PROMPT_VERSION,
            "voice_system_prompt": voice.system_prompt(),
            "minds": [json.loads(row["trace_json"]) for row in thoughts],
            "judge_system_prompt": judge.system_prompt(),
            "traces": [json.loads(row["trace_json"]) for row in rows],
            "assets": [{"asset_id": a["asset_id"], "object_id": a["object_id"], "status": a["status"],
                        "record": json.loads(a["record_json"]), "call": json.loads(a["trace_json"]),
                        "updated_at": a["updated_at"]} for a in assets],
            "model_calls": calls}


@app.post("/runs/{run_id}/assets/{asset_id}/retry")
def retry_asset(run_id: str, asset_id: str, background: BackgroundTasks):
    """Developer-only: repaint a failed sprite."""
    with _lock, db() as connection:
        _developer_run(connection, run_id)
        updated = connection.execute("UPDATE assets SET status='pending' WHERE asset_id=? AND run_id=?",
                                     (asset_id, run_id)).rowcount
    if not updated:
        raise HTTPException(404, "Unknown asset")
    background.add_task(_generate_asset, asset_id)
    return {"status": "pending"}


class SayRequest(BaseModel):
    model_config = {"extra": "forbid"}
    npc_id: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=talk.MAX_TEXT)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


def _talk_problem(state: dict, npc_id: str) -> tuple[dict, list[list[int]]]:
    """The person and the walk to reach them, or an HTTP 409 saying why they can't be spoken to."""
    npc = minds.find(state["npcs"], npc_id)
    if npc is None:
        raise HTTPException(404, "Unknown person")
    problem = talk.busy(npc)
    walk = talk.walk_to(state, npc) if problem is None else None
    if problem is None and walk is None:
        problem = f"{npc['name']} is too far away to talk to."
    if problem:
        raise HTTPException(409, {"reason": "cannot_talk", "message": problem})
    return npc, walk


class EncounterAct(BaseModel):
    model_config = {"extra": "forbid"}
    kind: Literal["say", "do", "wait", "leave", "yield"]
    text: str = Field(default="", max_length=600)
    target_id: str | None = Field(default=None, max_length=60)
    selected_ids: list[str] = Field(default_factory=list, max_length=12)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


@app.post("/runs/{run_id}/say")
def say(run_id: str, request: SayRequest, background: BackgroundTasks):
    """Speak to someone: a round of an encounter (a new one if they weren't already face to face)."""
    return _play_round(run_id, EncounterAct(kind="say", text=request.text, target_id=request.npc_id,
                                            expected_version=request.expected_version,
                                            request_id=request.request_id), background)


@app.post("/runs/{run_id}/encounter/act")
def encounter_act(run_id: str, request: EncounterAct, background: BackgroundTasks):
    """The stranger's part of a round: say, do, wait or walk away. Everyone's actions resolve together."""
    return _play_round(run_id, request, background)


def _round_setup(state: dict, request: EncounterAct) -> list[list[int]]:
    """Check the stranger can act in a round now; returns the walk to whoever they start talking to."""
    if request.kind == "say" and not request.text.strip():
        raise HTTPException(422, "Say something")
    current = encounter.active(state)
    if current is None:
        if request.kind != "say" or not request.target_id:
            raise HTTPException(409, {"reason": "no_encounter", "message": "Nobody is face to face with you."})
        return _talk_problem(state, request.target_id)[1]
    if request.target_id and request.target_id not in current["participants"]:
        npc = minds.find(state["npcs"], request.target_id)
        if npc is None:
            raise HTTPException(404, "Unknown person")
        problem = talk.busy(npc)
        if problem is None and math.dist(minds._cell(npc), minds.player_cell(state)) > talk.HEAR_TALK_CELLS:
            problem = "Deal with who is in front of you first."  # Face to face, you can call out, not walk off.
        if problem:
            raise HTTPException(409, {"reason": "cannot_talk", "message": problem})
    return []


def _round_draft(state: dict, run_id: str, request: EncounterAct, walk: list[list[int]], intents: dict,
                 judged: judge.JudgeCall | None) -> tuple[dict, dict]:
    """The physical part of a round on the latest world (deterministic: safe to redo after model calls)."""
    seen = talk.standing_at(state, walk)
    now = seen["sim_time_ms"]
    current = encounter.active(seen)
    if current is None:
        encounter.open_for_talk(seen, minds.find(seen["npcs"], request.target_id), now)
    elif request.target_id and request.target_id not in current["participants"]:
        encounter.join(seen, minds.find(seen["npcs"], request.target_id), "talk", None, now)
    for npc_id in encounter.missing_intents(seen):  # Anyone Jev didn't answer for keeps listening.
        encounter.set_intent(seen, minds.find(seen["npcs"], npc_id), intents.get(npc_id, {}))
    action = {"kind": request.kind, "text": request.text, "target_id": request.target_id}
    draft, record = encounter.resolve(seen, run_id, action, judged.result if judged else None,
                                      _service_message(judged) if judged else None, request.request_id)
    record["walk"] = walk
    return draft, record


def _speak(draft: dict, npc: dict, text: str, happened: str | None, ask: tuple[str, dict], run_id: str,
           allowed: bool) -> dict:
    """One person's reply in a round: Jev decides what they do, the voice says it (outside the lock)."""
    decided = decider.decide(*ask)
    out = {"decided": decided, "ask": ask, "happened": happened, "key": None, "context": None, "spoken": None}
    if decided.ok:
        out["key"] = talk.decided_reply(draft, npc, decided.answers, ask[1],
                                        seed=f"{run_id}:{draft['event_seq']}:{npc['id']}")
        out["context"] = talk.voice_context(draft, npc, text, out["key"], decided.answers, happened)
        out["spoken"] = voice.speak(out["context"], talk.fallback_line(draft, npc, out["key"]), allowed=allowed)
    return out


def _play_round(run_id: str, request: EncounterAct, background: BackgroundTasks) -> dict:
    started, timing = time.perf_counter(), {}
    request_json = json.dumps({"kind": request.kind, "text": request.text, "target_id": request.target_id,
                               "selected_ids": request.selected_ids}, sort_keys=True)
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        prior = connection.execute("SELECT final_seq,request_json FROM action_requests WHERE run_id=? AND request_id=?",
                                   (run_id, request.request_id)).fetchone()
        if prior:
            if prior["request_json"] != request_json:
                raise HTTPException(409, {"reason": "request_id_conflict"})
            replayed = state_at(connection, run, prior["final_seq"])
            return {"state": replayed, "duplicate": True, "round": replayed.get("last_round")}
        if connection.execute("SELECT 1 FROM events WHERE run_id=? AND request_id=?",
                              (run_id, request.request_id)).fetchone():
            raise HTTPException(409, {"reason": "request_id_conflict"})
        if _is_stale(state, request.expected_version):
            raise HTTPException(409, {"reason": "stale_state", "state": state})
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer interactive")
        if run["seed_version"] < 5:
            raise HTTPException(409, "This journey began before people could talk. Start a new journey to talk.")
        walk = _round_setup(state, request)
        if run_id in _crafting_runs:
            raise HTTPException(409, {"reason": "in_progress"})
        _crafting_runs.add(run_id)
        seen = talk.standing_at(state, walk)
        missing = encounter.missing_intents(seen)
        asking = encounter.intent_request(seen, missing) if missing else None
        context = crafting.build_context(seen, request.text, request.selected_ids) if request.kind == "do" else None
        calls_used = telemetry.calls_for_run(connection, run_id)
    try:
        # Everyone's intent for this round (usually decided already while the player typed) and the judge
        # for the stranger's attempt: both outside the lock, side by side.
        with ThreadPoolExecutor(max_workers=2) as pool:
            intent_job = pool.submit(decider.decide, asking[0], asking[1]) if asking else None
            judge_job = pool.submit(_judge, context, calls_used) if context else None
            intent_call = intent_job.result() if intent_job else None
            judged = judge_job.result() if judge_job else None
        timing["intents_ms"] = intent_call.latency_ms if intent_call else 0
        timing["judge_ms"] = judged.latency_ms if judged else 0
        intents = {n: minds.answers_for(intent_call.answers, asking[2][n]) for n in missing} \
            if intent_call and intent_call.ok else {}
        with _lock, db() as connection:
            run, state = load_run(connection, run_id)
            if _is_stale(state, request.expected_version):
                raise HTTPException(409, {"reason": "stale_state", "state": state})
            draft, record = _round_draft(state, run_id, request, walk, intents, judged)
            replier = minds.find(draft["npcs"], record["replier"]) if record["replier"] else None
            happened = " ".join(record["happened"]) or None
            text = request.text if request.kind == "say" else ""
            reply_ask = talk.request(draft, replier, text, happened) if replier else None
        # The person addressed replies to what actually happened; someone else may cut in after them.
        allowed = calls_used < ai_config.max_calls_per_run()
        speaking = time.perf_counter()
        main = _speak(draft, replier, text, happened, reply_ask, run_id, allowed) if reply_ask else None
        decided = main["decided"] if main else None
        spoken = main["spoken"] if main else None
        cutting_in = minds.find(draft["npcs"], record["interjector"]) if record["interjector"] else None
        side = None
        if cutting_in:
            heard = " ".join(filter(None, [happened, f"{replier['name']} just said: “{spoken.text}”" if spoken else None]))
            side = _speak(draft, cutting_in, "", heard, talk.request(draft, cutting_in, "", heard), run_id, allowed)
        timing["reply_decide_ms"] = main["decided"].latency_ms if main else 0
        timing["reply_voice_ms"] = main["spoken"].latency_ms if main and main["spoken"] else 0
        timing["speaking_ms"] = round((time.perf_counter() - speaking) * 1000)
        with _lock, db() as connection:
            run, state = load_run(connection, run_id)
            for call in (intent_call, decided, side["decided"] if side else None):
                if call is not None:
                    telemetry.record(connection, run_id, "decider", call.model, call.provider, call.latency_ms, call.ok,
                                     call.error or call.fallback_from, call.input_tokens, call.output_tokens)
            if judged and judged.attempts:
                telemetry.record(connection, run_id, "judge", judged.model, judged.prompt_version, judged.latency_ms,
                                 judged.status == "ok", judged.error, judged.input_tokens, judged.output_tokens,
                                 judged.attempts)
            for line in (spoken, side["spoken"] if side else None):
                if line and line.model and line.model != "stub":
                    telemetry.record(connection, run_id, "voice", line.model, line.prompt_version, line.latency_ms,
                                     line.status == "ok", line.error, line.input_tokens, line.output_tokens)
        if reply_ask and not (decided and decided.ok) and request.kind == "say" and not any(
                e["kind"] in ("strike", "flee", "leave", "shout_for_help", "whistle") for e in record["entries"]):
            raise HTTPException(503, {"reason": "decider_failed", "message": (
                f"{replier['name']} doesn't seem to hear you. (The decider couldn't be reached, so nothing changed.)")})
        with _lock, db() as connection:
            run, state = load_run(connection, run_id)
            if _is_stale(state, request.expected_version):
                raise HTTPException(409, {"reason": "stale_state", "state": state})
            walk = _round_setup(state, request)
            draft, record = _round_draft(state, run_id, request, walk, intents, judged)  # Redone on the latest world.
            now, replies, talk_trace = draft["sim_time_ms"], [], None
            for spoke, person, words, kind in ((main, replier, text, "reply"), (side, cutting_in, "", "interject")):
                if not (spoke and spoke["spoken"]) or record["replier" if kind == "reply" else "interjector"] \
                        != person["id"]:
                    continue
                said = talk.exchange(draft, person["id"], words, spoke["decided"].answers, spoke["key"],
                                     spoke["spoken"].text, [], spoke["happened"])
                draft.setdefault("learned", []).extend(said["learned"])
                draft["journal"].append(said["journal_entry"])
                replies.append({"npc_id": person["id"], "name": person["name"], "line": spoke["spoken"].text,
                                "kind": kind})
                trace = {"kind": "talk", "npc_id": person["id"], "text": words, "happened": spoke["happened"],
                         "action": spoke["key"], "jev_choice": (spoke["decided"].answers.get("reply") or {}).get("choice"),
                         "why": "addressed" if kind == "reply" else "cut in", "reply": spoke["spoken"].text,
                         "regard_change": said["regard_change"], "situation": spoke["ask"][0],
                         "questions": spoke["ask"][1], "call": spoke["decided"].as_dict(),
                         "voice": spoke["spoken"].as_dict(), "voice_context": spoke["context"]}
                talk_trace = talk_trace or trace
                if kind == "interject":
                    connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                                       (run_id, state["event_seq"] + 1, person["id"], json.dumps(trace)))
            encounter.finish(draft, record, now, replies)
            elapsed = encounter.round_ms(record)
            people = _advance_people(draft, elapsed)
            draft.update(npcs=people["npcs"], player=people["player"], pending_minds=people["pending_minds"],
                         encounter=people["encounter"], sim_time_ms=now + elapsed)
            draft["journal"].extend(people["people_journal"])
            payload = _round_payload(state, draft, record)
            payload["safe_seq"] = state["event_seq"] if minds.calm(state) else state.get("safe_seq", 0)
            append(connection, state, "round", payload, request.request_id, payload["sim_time_ms"] // 1000)
            _apply_round(state, payload)
            connection.execute("INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?)",
                               (run_id, request.request_id, state["event_seq"], request_json))
            craft_trace = None
            if record.get("verdict"):
                made = [state["objects"][i] for i in record["entry"].get("made_ids", []) if i in state["objects"]]
                craft_trace = _record_attempt(connection, run_id, request.request_id, state["event_seq"], request.text,
                                              request.selected_ids, context, judged, record["verdict"], made,
                                              background)
            round_trace = {"kind": "round", "npc_id": (replier or {}).get("id") or "encounter",
                           "why": f"round {record['round']}", "action": (main or {}).get("key") or request.kind,
                           "intents": record.get("intents"), "entries": record["entries"],
                           "situation": asking[0] if asking else "(Everyone's intents were decided earlier, while the "
                                                                 "stranger was choosing.)",
                           "questions": asking[1] if asking else {},
                           "call": intent_call.as_dict() if intent_call else {},
                           "timing": dict(timing, total_ms=round((time.perf_counter() - started) * 1000))}
            for trace in (talk_trace, round_trace):
                if trace:
                    connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                                       (run_id, state["event_seq"], trace["npc_id"], json.dumps(trace)))
    finally:
        _crafting_runs.discard(run_id)
    timing["total_ms"] = round((time.perf_counter() - started) * 1000)
    response = {"state": state, "duplicate": False, "round": state["last_round"], "timing": timing}
    if run["mode"] == "developer":
        response["trace"] = talk_trace or craft_trace
        response["craft_trace"] = craft_trace
    return response


class ThinkRequest(BaseModel):
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


_thinking_runs: set[str] = set()


@app.post("/runs/{run_id}/think")
def think(run_id: str, request: ThinkRequest):
    """Let people with something on their mind decide what to do (the decider runs outside the lock)."""
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        prior = connection.execute("SELECT seq FROM events WHERE run_id=? AND request_id=?",
                                   (run_id, request.request_id)).fetchone()
        if prior is not None:
            return {"state": state_at(connection, run, int(prior["seq"])), "duplicate": True}
        # Blows are resolved on the clock now; older saves may still hold "resolve_attack" entries.
        batch = [p for p in state.get("pending_minds", []) if p["kind"] in ("decide", "round")
                 and (npc := minds.find(state["npcs"], p["npc_id"])) and npc.get("alive", True)][:minds.THINK_BATCH]
        if not state.get("pending_minds"):
            return {"state": state, "duplicate": False}
        if run_id in _thinking_runs:
            raise HTTPException(409, {"reason": "in_progress"})
        _thinking_runs.add(run_id)
        shared = minds.batch_request(state, batch) if batch else None
    try:
        # One request for everyone deciding now; per-person requests only for anyone it left out.
        calls: dict[str, decider.DeciderCall] = {}
        answers: dict[str, dict] = {}
        if shared:
            text, questions, prefixes = shared
            batch_call = decider.decide(text, questions)
            calls["batch"] = batch_call
            for pending in batch:
                mine = minds.answers_for(batch_call.answers, prefixes[pending["npc_id"]])
                if batch_call.ok and "action" in mine:
                    answers[pending["npc_id"]] = mine
        missing = [pending for pending in batch if pending["npc_id"] not in answers]
        with _lock, db() as connection:
            _, snapshot = load_run(connection, run_id)
        for pending, call in zip(missing, decider.decide_many(
                [minds.decision_request(snapshot, pending) for pending in missing])):
            calls[pending["npc_id"]] = call
            if call.ok:
                answers[pending["npc_id"]] = call.answers
        with _lock, db() as connection:
            run, state = load_run(connection, run_id)
            for call in calls.values():
                telemetry.record(connection, run_id, "decider", call.model, call.provider, call.latency_ms, call.ok,
                                 call.error or call.fallback_from, call.input_tokens, call.output_tokens)
            working = copy.deepcopy(state)
            handled = {(p["npc_id"], p["kind"]) for p in batch}
            working["pending_minds"] = [p for p in working.get("pending_minds", [])
                                        if p["kind"] in ("decide", "round") and (p["npc_id"], p["kind"]) not in handled]
            now, heard, records = working["sim_time_ms"], [], []
            for pending in batch:
                npc = minds.find(working["npcs"], pending["npc_id"])
                call = calls.get(pending["npc_id"]) or calls.get("batch")
                record = {"npc_id": pending["npc_id"], "kind": pending["kind"], "why": pending["why"],
                          "skipped": None, "shared_request": pending["npc_id"] not in calls}
                if npc is None or not npc.get("alive", True):
                    record["skipped"] = "no longer alive"
                elif pending["npc_id"] not in answers:
                    record["skipped"] = f"decider failed: {call.error if call else 'no answer'}"
                elif pending["kind"] == "round":
                    if pending["npc_id"] in encounter.missing_intents(working):
                        record.update(encounter.set_intent(working, npc, answers[pending["npc_id"]]))
                    else:
                        record["skipped"] = "already committed this round"
                else:
                    record.update(minds.apply_decision(working, npc, answers[pending["npc_id"]], now, heard))
                records.append(record)
                situation, questions = (shared[0], {k: v for k, v in shared[1].items()
                                                    if k.startswith(shared[2][pending["npc_id"]])}) \
                    if record["shared_request"] and shared else minds.decision_request(snapshot, pending)
                trace = {**record, "situation": situation, "questions": questions,
                         "call": call.as_dict() if call else {}, "people_in_request": len(batch)}
                connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                                   (run_id, state["event_seq"] + 1, pending["npc_id"], json.dumps(trace)))
            payload = {"npcs": working["npcs"], "player": working["player"],
                       "pending_minds": working.get("pending_minds", []), "people_journal": heard,
                       "decisions": records, "encounter": working.get("encounter")}
            append(connection, state, "minds", payload, request.request_id, state["tick"])
            state["npcs"], state["player"] = payload["npcs"], payload["player"]
            _apply_people(state, payload)
    finally:
        _thinking_runs.discard(run_id)
    response = {"state": state, "duplicate": False}
    if run["mode"] == "developer":
        response["decisions"] = records
    return response


@app.post("/runs/{run_id}/rewind", status_code=201)
def rewind(run_id: str):
    """Copy this journey up to its last calm moment into a new run, leaving the original untouched."""
    with _lock, db() as connection:
        run, state = load_run(connection, run_id)
        point = int(state.get("safe_seq", 0))
        new_id = uuid4().hex
        connection.execute("INSERT INTO runs (id,mode,seed_version,geometry_version) VALUES (?,?,?,?)",
                           (new_id, run["mode"], run["seed_version"], run["geometry_version"]))
        connection.execute("INSERT INTO events (run_id,seq,tick,kind,payload,request_id) "
                           "SELECT ?,seq,tick,kind,payload,request_id FROM events WHERE run_id=? AND seq<=?",
                           (new_id, run_id, point))
        _, restored = load_run(connection, new_id)
    return restored


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
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer movable")
        if encounter.hostile(state):
            raise HTTPException(409, {"reason": "encounter_active", "state": state})
        cells = request.cells or ([[request.x, request.y]] if request.x is not None and request.y is not None else [])
        if not cells or any(len(cell) != 2 for cell in cells):
            raise HTTPException(422, "Send x and y, or a list of [x, y] cells")

        def passable(x: int, y: int) -> bool:
            if not (0 <= x <= 95 and 0 <= y <= 71):
                return False
            if 4 <= y <= 8:
                return 46 <= x <= 50 and state["gate_open"]
            if state["geometry_version"] >= 2:
                geometry = WORLD_GEOMETRY_V2 if state["geometry_version"] == 2 else WORLD_GEOMETRY
                cleared = crafting.cleared_obstacles(state)  # e.g. felled trees
                for building in geometry["buildings"] + geometry["obstacles"]:
                    if building["name"] in cleared:
                        continue
                    bx, by, width, height = building["cells"]
                    if bx <= x < bx + width and by <= y < by + height:
                        return False
            return True

        # Walk the cells in order; stop at the first illegal step, keeping the legal ones before it.
        x, y = state["player"]["x"], state["player"]["y"]
        accepted: list[list[int]] = []
        travel_ms, problem = 0, None
        speed = RUN_SPEED_CELLS_PER_SECOND if request.running else MOVE_SPEED_CELLS_PER_SECOND
        for nx, ny in cells:
            dx, dy = nx - x, ny - y
            if max(abs(dx), abs(dy)) != 1:
                problem = (422, "Move must cross exactly one adjacent cell")
            elif not passable(nx, ny):
                problem = (403, "A building, city wall, or closed gate blocks the path")
            elif dx and dy and (not passable(x + dx, y) or not passable(x, y + dy)):
                problem = (403, "Cannot cut diagonally through a blocked corner")
            if problem:
                break
            travel_ms += round(1000 * math.hypot(dx, dy) / speed) if run["seed_version"] < 3 else 0
            x, y = nx, ny
            accepted.append([x, y])
            if y <= 3:
                break  # Inside the city.
        if not accepted:
            raise HTTPException(*problem)
        sim_time_ms = state["sim_time_ms"] + travel_ms  # New runs use the exploration clock instead.
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
        append(connection, state, "move", payload, request.request_id, tick)
        state["sim_time_ms"] = sim_time_ms
        state["player"].update(x=x, y=y)
        if "encounter" in payload:
            state.update(encounter=payload["encounter"], npcs=payload["npcs"], pending_minds=payload["pending_minds"])
        if y <= 3 and not state["inside_city"]:
            append(connection, state, "objective_complete", {"location": "loc_city_interior"},
                   f"objective:{request.request_id}", tick)
            state["inside_city"] = True
        # Bound replay cost during continuous exploration. Events remain the source of truth.
        if state["event_seq"] % 64 == 0:
            connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                               (run_id, state["event_seq"], json.dumps(state, sort_keys=True)))
    if problem:
        return JSONResponse({"detail": problem[1], "state": state, "accepted": len(accepted)}, status_code=problem[0])
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
        if encounter.hostile(state):
            raise HTTPException(409, {"reason": "encounter_active", "state": state})
        sim_time_ms = state["sim_time_ms"] + request.elapsed_ms
        payload = {"sim_time_ms": sim_time_ms, **_advance_people(state, request.elapsed_ms)}
        append(connection, state, "explore", payload, request.request_id, sim_time_ms // 1000)
        state["sim_time_ms"] = sim_time_ms
        state["npcs"] = payload["npcs"]
        _apply_people(state, payload)
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
