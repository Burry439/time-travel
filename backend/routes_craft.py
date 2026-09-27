"""Try Something outside encounters, the quick pick up / put down, sprites, and developer traces."""
from __future__ import annotations

import json
import sqlite3
from typing import Callable, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import attempts
import crafting
import encounter
import minds
import rounds
import store
from ai import config as ai_config, decider, judge, telemetry, voice

router = APIRouter()


class CraftRequest(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(min_length=1, max_length=600)
    selected_ids: list[str] = Field(default_factory=list, max_length=12)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


class QuickRequest(BaseModel):
    model_config = {"extra": "forbid"}
    verb: Literal["take", "drop"]
    object_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


def _craft_response(run: sqlite3.Row, state: dict, trace: dict | None, duplicate: bool) -> dict:
    response = {"state": state, "duplicate": duplicate}
    if run["mode"] == "developer":
        response["trace"] = trace
    return response


def _load_trace(connection: sqlite3.Connection, run_id: str, request_id: str) -> dict | None:
    row = connection.execute("SELECT trace_json FROM craft_traces WHERE run_id=? AND request_id=?",
                             (run_id, request_id)).fetchone()
    return json.loads(row["trace_json"]) if row else None


@router.post("/runs/{run_id}/craft")
def craft(run_id: str, request: CraftRequest, background: BackgroundTasks):
    """Judge an attempt outside the lock, then revalidate and commit one event."""
    with store.db() as connection:
        _, peek = store.load_run(connection, run_id)
    if encounter.active(peek):  # Face to face with someone: this is the stranger's part of a round.
        return rounds.play_round(run_id, rounds.EncounterAct(kind="do", text=request.text,
                                                             selected_ids=request.selected_ids,
                                                             expected_version=request.expected_version,
                                                             request_id=request.request_id), background)
    return _attempt(run_id, request.text, request.selected_ids, request.expected_version, request.request_id,
                    background, lambda state, context, calls_used: attempts.judge_attempt(context, calls_used))


@router.post("/runs/{run_id}/quick")
def quick(run_id: str, request: QuickRequest, background: BackgroundTasks):
    """Pick up or put down (E, the bag's Put down): decided by code, no model; seen and saved like any attempt."""
    with store.db() as connection:
        _, peek = store.load_run(connection, run_id)
    if encounter.hostile(peek):
        raise HTTPException(409, {"reason": "encounter_active", "state": peek})
    return _attempt(run_id, f"{request.verb} {request.object_id}", [request.object_id], request.expected_version,
                    request.request_id, background,
                    lambda state, context, calls_used: judge.JudgeCall(
                        status="ok", model="code", result=crafting.quick(state, request.verb, request.object_id)))


def _attempt(run_id: str, text: str, selected_ids: list[str], expected_version: int, request_id: str,
             background: BackgroundTasks, propose: Callable[[dict, dict, int], judge.JudgeCall]) -> dict:
    request_json = json.dumps({"text": text, "selected_ids": selected_ids}, sort_keys=True)
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior = connection.execute("SELECT final_seq,request_json FROM action_requests WHERE run_id=? AND request_id=?",
                                   (run_id, request_id)).fetchone()
        if prior:
            if prior["request_json"] != request_json:
                raise HTTPException(409, {"reason": "request_id_conflict"})
            return _craft_response(run, store.state_at(connection, run, prior["final_seq"]),
                                   _load_trace(connection, run_id, request_id), duplicate=True)
        if connection.execute("SELECT 1 FROM events WHERE run_id=? AND request_id=?",
                              (run_id, request_id)).fetchone():
            raise HTTPException(409, {"reason": "request_id_conflict"})
        if store.is_stale(state, expected_version):
            raise HTTPException(409, {"reason": "stale_state", "state": state})
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer interactive")
        if run_id in attempts.busy_runs:
            raise HTTPException(409, {"reason": "in_progress"})
        attempts.busy_runs.add(run_id)
        context = crafting.build_context(state, text, selected_ids)
        calls_used = telemetry.calls_for_run(connection, run_id)
        snapshot = state
    try:
        # Any model call happens outside the lock and outside any transaction.
        judged = propose(snapshot, context, calls_used)
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            if judged.attempts:
                telemetry.record(connection, run_id, "judge", judged.model, judged.prompt_version, judged.latency_ms,
                                 judged.status == "ok", judged.error, judged.input_tokens, judged.output_tokens,
                                 judged.attempts)
            # Validation runs against the state as it is now, not the snapshot the judge saw,
            # one step at a time, stopping at the first step that does not succeed.
            payload, verdict, after = crafting.resolve_attempt(
                state, run_id, text, judged.result, attempts.service_message(judged), request_id,
                state["sim_time_ms"])
            payload["perceptions"] = minds.perceive(after, payload["journal_entry"])
            minds.apply_perceptions(after, payload["perceptions"])
            payload["safe_seq"] = state["event_seq"] if minds.calm(state) else state.get("safe_seq", 0)
            payload.update(store.advance_people(after, verdict["effort_seconds"] * 1000))
            store.append(connection, state, "craft", payload, request_id, payload["sim_time_ms"] // 1000)
            crafting.apply_payload(state, payload)
            store.apply_people(state, payload)
            connection.execute("INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?)",
                               (run_id, request_id, state["event_seq"], request_json))
            new_objects = [obj for step in payload["steps"] for obj in step["new_objects"]]
            trace = None if judged.model == "code" else attempts.record_attempt(  # No model: nothing to trace.
                connection, run_id, request_id, state["event_seq"], text, selected_ids, context, judged, verdict,
                new_objects, background)
    finally:
        attempts.busy_runs.discard(run_id)
    return _craft_response(run, state, trace, duplicate=False)


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, background: BackgroundTasks):
    """200 PNG when painted, 202 while painting, 404 with a status when there is no picture."""
    if not attempts.ASSET_ID.match(asset_id):
        raise HTTPException(404, "Unknown asset")
    with store.db() as connection:
        row = connection.execute("SELECT status,trace_json FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Unknown asset")
        status = row["status"]
        path = attempts.ASSET_DIR / f"{asset_id}.png"
        if status == "ready" and path.exists():
            return FileResponse(path, media_type="image/png")
        if status == "disabled" and ai_config.images_enabled():
            connection.execute("UPDATE assets SET status='pending' WHERE asset_id=?", (asset_id,))
            status = "pending"
    if status == "pending":
        with attempts.asset_jobs_lock:
            running = asset_id in attempts.asset_jobs
        if not running:  # e.g. the backend restarted while painting
            background.add_task(attempts._generate_asset, asset_id)
        return JSONResponse({"status": "pending"}, status_code=202)
    return JSONResponse({"status": status, "error": json.loads(row["trace_json"]).get("error")}, status_code=404)


def _developer_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404, "Run not found")
    if run["mode"] != "developer":
        raise HTTPException(403, "AI traces are available in developer playtests only")
    return run


@router.get("/runs/{run_id}/traces")
def get_traces(run_id: str, limit: int = 10):
    """Developer view of recent judge calls, validator decisions, sprites, and model telemetry."""
    with store.db() as connection:
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


@router.post("/runs/{run_id}/assets/{asset_id}/retry")
def retry_asset(run_id: str, asset_id: str, background: BackgroundTasks):
    """Developer-only: repaint a failed sprite."""
    with store.lock, store.db() as connection:
        _developer_run(connection, run_id)
        updated = connection.execute("UPDATE assets SET status='pending' WHERE asset_id=? AND run_id=?",
                                     (asset_id, run_id)).rowcount
    if not updated:
        raise HTTPException(404, "Unknown asset")
    background.add_task(attempts._generate_asset, asset_id)
    return {"status": "pending"}
