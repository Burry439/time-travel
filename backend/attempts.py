"""What every Try Something shares, in the open world or in an encounter round: the judge call,
the developer trace, and painting a sprite for anything new (presentation, outside the event log)."""
from __future__ import annotations

import json
import re
import sqlite3
import threading

from fastapi import BackgroundTasks

import store
from ai import config as ai_config, illustrator, judge, telemetry

ASSET_DIR = store.ROOT / "data" / "assets"
ASSET_ID = re.compile(r"^spr_[0-9a-f]{8}_[a-z0-9_]+$")
busy_runs: set[str] = set()  # Journeys with a Try Something, conversation or round in flight.
asset_jobs: set[str] = set()
asset_jobs_lock = threading.Lock()


def service_message(judged: judge.JudgeCall) -> str | None:
    if judged.status == "disabled":
        return "AI crafting isn't set up on this computer yet. Add OPENAI_API_KEY to backend/.env and restart the backend."
    if judged.status == "capped":
        return "This journey has used its allowance of AI calls, so nothing was judged. Nothing changed."
    if judged.status == "error":
        return "The judge couldn't be reached, so nothing was decided and nothing changed."
    return None


def record_attempt(connection: sqlite3.Connection, run_id: str, request_id: str, event_seq: int, text: str,
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


def judge_attempt(context: dict, calls_used: int) -> judge.JudgeCall:
    if calls_used >= ai_config.max_calls_per_run():
        return judge.JudgeCall(status="capped", error=f"Reached MAX_MODEL_CALLS_PER_RUN ({calls_used}).")
    return judge.judge_craft(context)


def _generate_asset(asset_id: str) -> None:
    """Paint one sprite. Runs after the response; failure leaves the placeholder in play."""
    with asset_jobs_lock:
        if asset_id in asset_jobs:
            return
        asset_jobs.add(asset_id)
    try:
        with store.db() as connection:
            row = connection.execute("SELECT run_id,record_json FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None:
            return
        try:
            call = illustrator.generate_sprite(json.loads(row["record_json"]), ASSET_DIR / f"{asset_id}.png")
        except Exception as error:  # Never leave a job silently pending (it would be re-queued forever).
            call = illustrator.SpriteCall(status="failed", error=f"{type(error).__name__}: {error}")
        with store.lock, store.db() as connection:
            connection.execute("UPDATE assets SET status=?,trace_json=?,updated_at=CURRENT_TIMESTAMP WHERE asset_id=?",
                               (call.status, json.dumps(call.as_dict()), asset_id))
            if call.model:
                telemetry.record(connection, row["run_id"], "illustrator", call.model, call.prompt_version,
                                 call.latency_ms, call.status == "ready", call.error)
    finally:
        with asset_jobs_lock:
            asset_jobs.discard(asset_id)
