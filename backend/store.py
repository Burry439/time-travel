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
import zlib
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

import content
import m2
import npc_sim
import patch
import tutorial
from shapes import State

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "demo.sqlite3"))
WORLD_GEOMETRY = content.GEOMETRY
GEOMETRY_VERSION = WORLD_GEOMETRY["version"]
# 4 adds loose road materials and material data for crafting; 5 adds materials across the map,
# fellable trees and saplings, and NPC health; 6 adds people's own stock (Darin's lodestone, Mara's
# needles, Hessa's bowls) and the gate trough; 7 adds the gate beam and its brackets, and Tomas's rope,
# ladder and fulcrum stone.
SEED_VERSION = (
    12  # 8: the forge and the inn's cooking fire (heat). 9: the cracked bar holds the gate shut. 10: gear (D-49).
)
# 11: the old wainwright's yard, a free stock of materials for weapons and armour (D-51).
# 12: the wainwright's notebook, a readable recipe book (D-52).
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
# A journey replays on the world it began with, so a new starting world (a seed bump) retires the journeys
# begun on an older one (GDD D-04: no save compatibility between prototypes; D-58).
OLDEST_SEED = SEED_VERSION
SAVE_FORMAT = 2  # 2: events store only what changed (D-58). Journeys saved in an older format are retired too.
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
            CREATE TABLE IF NOT EXISTS item_library (
                signature TEXT NOT NULL,
                view TEXT NOT NULL,
                file TEXT NOT NULL,
                record_json TEXT NOT NULL DEFAULT '{}',
                uses INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(signature, view)
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
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
        if "scenario" not in columns:  # village (the game) or tutorial (D-50)
            connection.execute("ALTER TABLE runs ADD COLUMN scenario TEXT NOT NULL DEFAULT 'village'")
        if "save_format" not in columns:  # How its events are stored (D-58); journeys from before say 1.
            connection.execute("ALTER TABLE runs ADD COLUMN save_format INTEGER NOT NULL DEFAULT 1")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initial_state(run: sqlite3.Row) -> dict:
    state = {
        "run_id": run["id"],
        "mode": run["mode"],
        "seed_version": run["seed_version"],
        "scenario": run["scenario"] if "scenario" in run.keys() else "village",  # noqa: SIM118 (a sqlite3.Row)
        "geometry_version": run["geometry_version"],
        "event_seq": 0,
        "tick": 0,
        "sim_time_ms": 0,
        "player": {"x": 48, "y": 68, "alive": True},
        "gate_open": False,
        "inside_city": False,
        "objective": "Get inside the city",
        "npcs": npc_sim.seed_npcs(NPCS + PATROL_GUARDS),
    }
    state.update(m2.seed_m2())
    for npc in state["npcs"]:
        npc.update(alive=True, health=100, injuries=[])
    people = {n["id"]: n for n in state["npcs"]} | {"player": state["player"]}
    for obj in state["objects"].values():  # Everyone starts wearing and holding their own gear (D-49).
        for slot in obj.pop("worn_slots", []):
            people[obj["holder_id"]].setdefault("equipped", {})[slot] = obj["id"]
    if state["scenario"] == "tutorial":  # The first morning, with the device (D-50).
        tutorial.setup(state)
    return state


# Events the player causes. A request is stale only if the client hasn't seen the latest of
# these; people thinking or the clock ticking in between never makes the player's request stale.
PLAYER_KINDS = {
    "move",
    "physical_action",
    "craft",
    "talk",
    "round",
    "fight",
    "gear",
    "dev_gate",
    "objective_complete",
    "device",
}


def is_stale(state: State, expected_version: int) -> bool:
    return not state.get("player_seq", 0) <= expected_version <= state["event_seq"]


def reduce_event(state: State, event: sqlite3.Row) -> None:
    """Every event is what changed (GDD D-58): apply it, then the counters."""
    patch.apply(state, payload_of(event)["patch"])
    if event["kind"] in PLAYER_KINDS:
        state["player_seq"] = event["seq"]
    state["event_seq"] = event["seq"]
    state["tick"] = event["tick"]


def apply_people(state: State, payload: dict) -> None:
    """Fields shared by events in which people act: their pending thoughts, what the player heard,
    and the latest calm moment to rewind to."""
    if "pending_minds" in payload:
        state["pending_minds"] = payload["pending_minds"]
    if "player" in payload:
        state["player"] = payload["player"]  # e.g. struck by someone during this time
    state["journal"].extend(payload.get("people_journal", []))
    for obj in payload.get("objects_added") or []:  # e.g. an arrow lying where it fell (D-49).
        state["objects"][obj["id"]] = dict(obj)
    for object_id, fields in (payload.get("objects_changed") or {}).items():  # Cooling, fires burning down.
        if object_id in state.get("objects", {}):
            state["objects"][object_id].update(fields)
    if "projectiles" in payload:
        state["projectiles"] = payload["projectiles"]
    state.setdefault("learned", []).extend(payload.get("learned_added", []))  # e.g. gossip the stranger overheard
    if "village" in payload:
        state["village"] = payload["village"]
    if "safe_seq" in payload:
        state["safe_seq"] = payload["safe_seq"]
    if "encounter" in payload:
        state["encounter"] = payload["encounter"]
    if "fight" in payload:
        state["fight"] = payload["fight"]
    if "barred_until" in payload:  # e.g. arrested after giving up a fight
        state["barred_until"] = payload["barred_until"]


def load_run(connection: sqlite3.Connection, run_id: str) -> tuple[sqlite3.Row, dict]:
    run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404, "Run not found")
    if run["seed_version"] < OLDEST_SEED or run["save_format"] < SAVE_FORMAT:
        raise HTTPException(410, "This journey is from an older version of the game. Start a new journey.")
    checkpoint = connection.execute(
        "SELECT seq,state_json FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)
    ).fetchone()
    state = json.loads(checkpoint["state_json"]) if checkpoint else initial_state(run)
    for event in connection.execute(
        "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, state["event_seq"])
    ):
        reduce_event(state, event)
    return run, state


def state_at(connection: sqlite3.Connection, run: sqlite3.Row, sequence: int) -> dict:
    """Reconstruct the exact saved result for an idempotent retry."""
    checkpoint = connection.execute(
        "SELECT seq,state_json FROM checkpoints WHERE run_id=? AND seq<=? ORDER BY seq DESC LIMIT 1",
        (run["id"], sequence),
    ).fetchone()
    state = json.loads(checkpoint["state_json"]) if checkpoint else initial_state(run)
    for event in connection.execute(
        "SELECT * FROM events WHERE run_id=? AND seq>? AND seq<=? ORDER BY seq",
        (run["id"], state["event_seq"], sequence),
    ):
        reduce_event(state, event)
    return state


COUNTERS = ("event_seq", "tick", "player_seq")  # Set from the event row itself, never saved in a patch.


def record(
    connection: sqlite3.Connection,
    before: dict,
    state: State,
    kind: str,
    request_id: str,
    tick: int,
    meta: dict | None = None,
) -> dict:
    """Save one event: what changed from ``before`` (a snapshot of the state as last saved) to ``state``. The counters
    move on; returns the new snapshot, so a request that saves twice passes it to the second record (GDD D-58).
    meta: details kept beside the change for the developer's event log (never applied)."""
    after = patch.snapshot(state)
    changes = {key: change for key, change in patch.diff(before, after).items() if key not in COUNTERS}
    sequence = state["event_seq"] + 1
    connection.execute(
        "INSERT INTO events (run_id, seq, tick, kind, payload, request_id) VALUES (?,?,?,?,?,?)",
        (
            state["run_id"],
            sequence,
            tick,
            kind,
            pack({**(meta or {}), "patch": changes}),
            request_id,
        ),
    )
    for snap in (state, after):
        snap["event_seq"] = sequence
        if kind in PLAYER_KINDS:
            snap["player_seq"] = sequence
        snap["tick"] = tick
    if sequence % CHECKPOINT_EVERY == 0:
        save_checkpoint(connection, after)
    return after


def pack(payload: dict) -> bytes:
    """An event's payload as stored: compressed JSON (about a third of the size, D-58)."""
    return zlib.compress(json.dumps(payload, sort_keys=True).encode("utf-8"), 6)


def payload_of(event: sqlite3.Row) -> dict:
    return json.loads(zlib.decompress(event["payload"]).decode("utf-8"))


CHECKPOINT_EVERY = 512  # Replaying a change is cheap; a full copy now and then bounds it (GDD D-58).
CHECKPOINTS_KEPT = 2


def save_checkpoint(connection: sqlite3.Connection, state: State) -> None:
    """A full copy of the journey at this event; only the newest few are kept (events stay the source of truth)."""
    connection.execute(
        "INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
        (state["run_id"], state["event_seq"], json.dumps(state, sort_keys=True)),
    )
    connection.execute(
        "DELETE FROM checkpoints WHERE run_id=? AND seq NOT IN "
        "(SELECT seq FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT ?)",
        (state["run_id"], state["run_id"], CHECKPOINTS_KEPT),
    )


def check_request(connection: sqlite3.Connection, state: State, expected_version: int, request_id: str) -> int | None:
    """The last event a repeat of this request already saved (its own and any it saved after, id+1, id+2...), or
    None; a new request from a stale view is refused (409)."""
    prior = connection.execute(
        "SELECT MAX(seq) AS seq FROM events WHERE run_id=? AND (request_id=? OR substr(request_id, 1, ?)=?)",
        (state["run_id"], request_id, len(request_id) + 1, request_id + "+"),
    ).fetchone()
    if prior["seq"] is not None:
        return int(prior["seq"])
    if is_stale(state, expected_version):
        raise HTTPException(409, {"reason": "stale_state", "state": state})
    return None
