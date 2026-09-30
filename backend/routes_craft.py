"""Try Something outside encounters, the quick pick up / put down, sprites, and developer traces."""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from collections.abc import Callable
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import attempts
import cast
import clock
import combat
import commands
import consequences
import crafting
import encounter
import intent
import judge_view
import perception
import reputation
import rounds
import routes_tutorial
import store
import tuning
from ai import config as ai_config
from ai import decider, judge, telemetry, voice

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
    row = connection.execute(
        "SELECT trace_json FROM craft_traces WHERE run_id=? AND request_id=?", (run_id, request_id)
    ).fetchone()
    return json.loads(row["trace_json"]) if row else None


@router.post("/runs/{run_id}/craft")
def craft(run_id: str, request: CraftRequest, background: BackgroundTasks):
    """Judge an attempt outside the lock, then revalidate and commit one event."""
    with commands.peek(run_id) as peek:
        face_to_face = encounter.active(peek)
    if face_to_face:  # Face to face with someone: this is the stranger's part of a round.
        return rounds.play_round(
            run_id,
            rounds.EncounterAct(
                kind="do",
                text=request.text,
                selected_ids=request.selected_ids,
                expected_version=request.expected_version,
                request_id=request.request_id,
            ),
            background,
        )
    return _attempt(
        run_id,
        request.text,
        request.selected_ids,
        request.expected_version,
        request.request_id,
        background,
        lambda state, context, calls_used: attempts.judge_attempt(context, calls_used),
    )


class ActRequest(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(min_length=1, max_length=600)
    target_id: str | None = Field(default=None, max_length=60)
    selected_ids: list[str] = Field(default_factory=list, max_length=12)
    mode: Literal["say", "do"] | None = None  # The bar's Say/Do toggle (D-55); None: the game works it out.
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


@router.post("/runs/{run_id}/act")
def act(run_id: str, request: ActRequest, background: BackgroundTasks):
    """Whatever the stranger typed: words, a deed, both, or waiting / giving up / walking away (GDD D-34)."""
    with commands.peek(run_id) as state:
        current = encounter.active(state)
    here = cast.player_cell(state)
    near = sorted(
        (n for n in state["npcs"] if n.get("alive", True) and cast.distance(n, here) <= tuning.HEAR_TALK_CELLS),
        key=lambda n: cast.distance(n, here),
    )
    target = request.target_id or (current.get("opened_by") if current else None)
    if target == "player":  # A conversation the stranger began: whoever they last addressed answers.
        target = None
    talking_with = [n["name"] for i in (current or {}).get("participants", []) if (n := cast.find(state["npcs"], i))]
    if request.mode:  # The player said which it is: no guessing, no model call (D-55).
        kind, how, call = intent.explicit(request.text, request.mode), "player", None
    else:
        kind, how, call = intent.classify(
            request.text, bool(current) or bool(near) or bool(request.target_id), talking_with
        )
    if call is not None:
        with store.lock, store.db() as connection:
            telemetry.log(connection, run_id, "decider", call)
    heard = {"kind": kind, "how": how}
    if combat.active(state) and kind in ("yield", "wait", "leave"):  # Giving up, holding still or running (D-41).
        return {**_fight_words(run_id, request, kind, state), "intent": heard}
    # Words and deeds still reach people mid-fight (D-51): a fight is only some people attacking the stranger.
    if not current and kind in ("do", "both"):
        # A deed shown or handed to someone nearby ("I show Roderic the compass") is a round with them, so they answer (D-48).
        target = request.target_id or named(request.text, near)
        if kind == "both" and not target and near:  # Words said aloud as you do it: the nearest person hears (D-57).
            target = near[0]["id"]
    if current or kind == "say" or (kind in ("do", "both") and target):
        if not current:
            target = target or (near[0]["id"] if near else None)
            if kind == "say" and not target:
                raise HTTPException(
                    409, {"reason": "nobody_hears", "message": "Nobody is close enough to hear you.", "intent": heard}
                )
        if not current and kind in ("wait", "yield", "leave"):
            return {"state": state, "duplicate": False, "intent": heard, "notice": "Nothing happens."}
        round_kind = {"both": "do"}.get(kind, kind)
        reply = rounds.play_round(
            run_id,
            rounds.EncounterAct(
                kind=round_kind,
                text=intent.unquote(request.text) if kind == "say" else request.text,
                target_id=target,
                selected_ids=request.selected_ids,
                expected_version=request.expected_version,
                request_id=request.request_id,
                speech=kind == "both",
            ),
            background,
        )
    elif kind in ("wait", "yield", "leave"):
        return {"state": state, "duplicate": False, "intent": heard, "notice": "Nothing happens."}
    else:  # A deed (or a deed with words) with nobody face to face: Try Something.
        reply = craft(
            run_id,
            CraftRequest(
                text=request.text,
                selected_ids=request.selected_ids,
                expected_version=request.expected_version,
                request_id=request.request_id,
            ),
            background,
        )
    return {**reply, "intent": heard}


def named(text: str, near: list[dict]) -> str | None:
    """The nearby person the words name, allowing for a misspelling ("Rodric"), or None."""
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 3]
    for npc in near:
        name = npc["name"].split()[0].lower()
        if any(w == name or (len(w) >= 4 and difflib.SequenceMatcher(None, w, name).ratio() >= 0.8) for w in words):
            return npc["id"]
    return None


def _fight_words(run_id: str, request: ActRequest, kind: str, seen: dict) -> dict:
    """Giving up in a fight is an event (guards arrest you); holding still or running are yours to do."""
    if kind != "yield":
        return {
            "state": seen,
            "duplicate": False,
            "notice": {"wait": "You hold still. They don't.", "leave": "Then run: get out of their reach."}[kind],
        }
    try:
        with commands.open(run_id, request, playable=False) as cmd:
            if not combat.active(cmd.state):
                return {"state": cmd.state, "duplicate": False, "notice": "The fight is already over."}
            outcome = encounter.surrender(cmd.state, cmd.state["sim_time_ms"])
            cmd.save("fight", cmd.state["tick"])
    except commands.Reply as reply:
        return reply.body
    return {"state": cmd.state, "duplicate": False, "notice": outcome["text"]}


@router.post("/runs/{run_id}/quick")
def quick(run_id: str, request: QuickRequest, background: BackgroundTasks):
    """Pick up or put down (E, the bag's Put down): decided by code, no model; seen and saved like any attempt."""
    with commands.peek(run_id) as peek:
        if encounter.hostile(peek):
            raise HTTPException(409, {"reason": "encounter_active", "state": peek})
    return _attempt(
        run_id,
        f"{request.verb} {request.object_id}",
        [request.object_id],
        request.expected_version,
        request.request_id,
        background,
        lambda state, context, calls_used: judge.JudgeCall(
            status="ok", model="code", result=crafting.quick(state, request.verb, request.object_id)
        ),
    )


def _attempt(
    run_id: str,
    text: str,
    selected_ids: list[str],
    expected_version: int,
    request_id: str,
    background: BackgroundTasks,
    propose: Callable[[dict, dict, int], judge.JudgeCall],
) -> dict:
    request = SimpleNamespace(expected_version=expected_version, request_id=request_id)
    body = {"text": text, "selected_ids": selected_ids}

    def repeated(run: sqlite3.Row, saved: dict, connection: sqlite3.Connection) -> dict:
        return _craft_response(run, saved, _load_trace(connection, run_id, request_id), duplicate=True)

    try:
        with commands.open(run_id, request, body=body, duplicate=repeated) as cmd:
            cmd.claim()
            context = judge_view.build_context(cmd.state, text, selected_ids)
            calls_used = telemetry.calls_for_run(cmd.connection, run_id)
            seen = cmd.state
    except commands.Reply as reply:
        return reply.body
    try:
        judged = propose(seen, context, calls_used)  # Any model call happens outside the lock.
        with commands.reopen(run_id, request, body=body, stale=False) as cmd:
            state = cmd.state
            if judged.attempts:
                telemetry.log(cmd.connection, run_id, "judge", judged)
            # Validation runs against the state as it is now, not the snapshot the judge saw,
            # one step at a time, stopping at the first step that does not succeed.
            payload, verdict, after = consequences.resolve_attempt(
                state, run_id, text, judged.result, attempts.service_message(judged), request_id, state["sim_time_ms"]
            )
            payload["perceptions"] = perception.perceive(after, payload["journal_entry"])
            perception.apply_perceptions(after, payload["perceptions"])
            reputation.after_deed(after, payload["journal_entry"])  # e.g. giving someone back their own things (D-46)
            payload["safe_seq"] = state["event_seq"] if cast.calm(state) else state.get("safe_seq", 0)
            payload.update(clock.advance_people(after, verdict["effort_seconds"] * 1000))
            consequences.apply_payload(state, payload)
            store.apply_people(state, payload)
            cmd.save("craft", payload["sim_time_ms"] // 1000)
            new_objects = [obj for step in payload["steps"] for obj in step["new_objects"]]
            trace = (
                None
                if judged.model == "code"  # No model: nothing to trace.
                else attempts.record_attempt(
                    cmd.connection,
                    run_id,
                    request_id,
                    state["event_seq"],
                    text,
                    selected_ids,
                    context,
                    judged,
                    verdict,
                    new_objects,
                    background,
                )
            )
    finally:
        commands.release(run_id)
    routes_tutorial.after_action(state)  # The tutorial may move on (D-50).
    return _craft_response(cmd.run, state, trace, duplicate=False)


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
            background.add_task(attempts.generate_asset, asset_id)
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
        rows = connection.execute(
            "SELECT trace_json FROM craft_traces WHERE run_id=? ORDER BY rowid DESC LIMIT ?",
            (run_id, max(1, min(limit, 50))),
        ).fetchall()
        assets = connection.execute(
            "SELECT asset_id,object_id,status,record_json,trace_json,updated_at FROM assets "
            "WHERE run_id=? ORDER BY rowid DESC LIMIT 20",
            (run_id,),
        ).fetchall()
        calls = telemetry.recent(connection, run_id)
        thoughts = connection.execute(
            "SELECT trace_json FROM mind_traces WHERE run_id=? ORDER BY id DESC LIMIT 20", (run_id,)
        ).fetchall()
    return {
        "ai": {**ai_config.status(), **decider.status()},
        "judge_prompt_version": judge.PROMPT_VERSION,
        "voice_system_prompt": voice.system_prompt(),
        "minds": [json.loads(row["trace_json"]) for row in thoughts],
        "judge_system_prompt": judge.system_prompt(),
        "traces": [json.loads(row["trace_json"]) for row in rows],
        "assets": [
            {
                "asset_id": a["asset_id"],
                "object_id": a["object_id"],
                "status": a["status"],
                "record": json.loads(a["record_json"]),
                "call": json.loads(a["trace_json"]),
                "updated_at": a["updated_at"],
            }
            for a in assets
        ],
        "model_calls": calls,
    }


@router.post("/runs/{run_id}/assets/{asset_id}/retry")
def retry_asset(run_id: str, asset_id: str, background: BackgroundTasks):
    """Developer-only: repaint a failed sprite."""
    with store.lock, store.db() as connection:
        _developer_run(connection, run_id)
        updated = connection.execute(
            "UPDATE assets SET status='pending' WHERE asset_id=? AND run_id=?", (asset_id, run_id)
        ).rowcount
    if not updated:
        raise HTTPException(404, "Unknown asset")
    background.add_task(attempts.generate_asset, asset_id)
    return {"status": "pending"}
