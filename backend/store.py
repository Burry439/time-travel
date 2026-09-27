"""The save: an append-only event log per journey, replayed into the world's state.

Every change to the world is an event; state is rebuilt by replaying events (with checkpoints).
Requests are idempotent by request id and rejected as stale when the player hasn't seen their own
latest action. Journeys begun before OLDEST_SEED are retired (GDD D-04).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

import crafting
import m2
import minds
import npc_sim
import talk

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "demo.sqlite3"))
WORLD_GEOMETRY = json.loads((ROOT / "data" / "world_geometry.json").read_text())
GEOMETRY_VERSION = WORLD_GEOMETRY["version"]
# 4 adds loose road materials and material data for crafting; 5 adds materials across the map,
# fellable trees and saplings, and NPC health; 6 adds people's own stock (Darin's lodestone, Mara's
# needles, Hessa's bowls) and the gate trough; 7 adds the gate beam and its brackets, and Tomas's rope,
# ladder and fulcrum stone.
SEED_VERSION = 7
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
OLDEST_SEED = 5  # Journeys begun before this are retired (GDD D-04: no save compatibility between prototypes).
lock = threading.RLock()


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
        "npcs": npc_sim.seed_npcs(NPCS + PATROL_GUARDS, WORLD_GEOMETRY),
    }
    state.update(m2.seed_m2(run["seed_version"]))
    for npc in state["npcs"]:
        npc.update(alive=True, health=100, injuries=[])
    return state


# Events the player causes. A request is stale only if the client hasn't seen the latest of
# these; people thinking or the clock ticking in between never makes the player's request stale.
PLAYER_KINDS = {"move", "physical_action", "craft", "talk", "round", "dev_gate", "objective_complete"}


def is_stale(state: dict, expected_version: int) -> bool:
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
        apply_people(state, payload)
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
        apply_people(state, payload)
    elif event["kind"] == "craft":
        crafting.apply_payload(state, payload)
        apply_people(state, payload)
    elif event["kind"] == "round":
        apply_round(state, payload)
    elif event["kind"] == "talk":
        talk.apply_payload(state, payload)
        apply_people(state, payload)
    elif event["kind"] == "minds":
        state["npcs"] = payload["npcs"]
        state["player"] = payload["player"]
        apply_people(state, payload)
    else:
        raise ValueError(f"Unknown event kind {event['kind']}")
    state["event_seq"] = event["seq"]
    state["tick"] = event["tick"]


def apply_people(state: dict, payload: dict) -> None:
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


def round_payload(before: dict, after: dict, record: dict) -> dict:
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


def apply_round(state: dict, payload: dict) -> None:
    for key in ROUND_FIELDS:
        state[key] = payload[key]
    state["journal"].extend(payload["journal_added"])
    state.setdefault("learned", []).extend(payload["learned_added"])
    if payload.get("admitted"):
        state["admitted"] = payload["admitted"]
    if "safe_seq" in payload:
        state["safe_seq"] = payload["safe_seq"]
    state["last_round"] = payload["round"]

def advance_people(state: dict, elapsed_ms: int) -> dict:
    """Payload fields for time passing: routines, the jobs people chose, encounters starting."""
    probe = dict(state)
    probe["pending_minds"] = list(state.get("pending_minds", []))
    npcs, heard, player = minds.advance_world(probe, elapsed_ms, state["sim_time_ms"])
    return {"npcs": npcs, "player": player, "pending_minds": probe["pending_minds"], "people_journal": heard,
            "encounter": probe.get("encounter")}


def load_run(connection: sqlite3.Connection, run_id: str) -> tuple[sqlite3.Row, dict]:
    run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404, "Run not found")
    if run["seed_version"] < OLDEST_SEED:
        raise HTTPException(410, "This journey is from an older version of the game. Start a new journey.")
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


def check_request(connection: sqlite3.Connection, state: dict, expected_version: int,
                  request_id: str) -> int | None:
    prior = connection.execute(
        "SELECT seq FROM events WHERE run_id=? AND request_id=?", (state["run_id"], request_id)
    ).fetchone()
    if prior:
        return int(prior["seq"])
    if is_stale(state, expected_version):
        raise HTTPException(409, {"reason": "stale_state", "state": state})
    return None
