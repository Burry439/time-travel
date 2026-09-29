"""Talking and encounter rounds: the stranger's part of a round, then the scene's answer (D-48).

/say and /encounter/act both play one round (encounter.py has the rules). The stranger acts; then one
voice call writes the group's moment: the person addressed and anyone else in the conversation or near
enough to join it say what they would say and do, in order. Code checks each line (the speaker is really
there, the move is theirs to make) and applies it as that person's exchange. Model calls run outside the
lock and the round is redone on the latest world before it is committed as one event.
"""
from __future__ import annotations

import json
import math
import time
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

import attempts
import combat
import crafting
import encounter
import minds
import store
import talk
from ai import config as ai_config, judge, telemetry, voice

router = APIRouter()


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
    speech: bool = False  # A deed that also says something: the reply hears the words too.


@router.post("/runs/{run_id}/say")
def say(run_id: str, request: SayRequest, background: BackgroundTasks):
    """Speak to someone: a round of an encounter (a new one if they weren't already face to face)."""
    return play_round(run_id, EncounterAct(kind="say", text=request.text, target_id=request.npc_id,
                                            expected_version=request.expected_version,
                                            request_id=request.request_id), background)


@router.post("/runs/{run_id}/encounter/act")
def encounter_act(run_id: str, request: EncounterAct, background: BackgroundTasks):
    """The stranger's part of a round: say, do, wait, give up or walk away; then the scene answers."""
    return play_round(run_id, request, background)


def _round_setup(state: dict, request: EncounterAct) -> list[list[int]]:
    """Check the stranger can act in a round now; returns the walk to whoever they start talking to."""
    if request.kind == "say" and not request.text.strip():
        raise HTTPException(422, "Say something")
    current = encounter.active(state)
    if current is None:
        if request.kind not in ("say", "do") or not request.target_id:
            raise HTTPException(409, {"reason": "no_encounter", "message": "Nobody is face to face with you."})
        return _talk_problem(state, request.target_id)[1]  # Speaking or showing something to someone.
    if request.target_id and request.target_id not in current["participants"]:
        npc = minds.find(state["npcs"], request.target_id)
        if npc is None:
            raise HTTPException(404, "Unknown person")
        problem = talk.busy(npc)
        if problem is None and math.dist(minds._cell(npc), minds.player_cell(state)) > talk.HEAR_TALK_CELLS:
            if not encounter.hostile(state):  # A friendly talk moves with you: walk over to them (D-48).
                return _talk_problem(state, request.target_id)[1]
            problem = "Deal with who is in front of you first."  # Confronted, you can call out, not walk off.
        if problem:
            raise HTTPException(409, {"reason": "cannot_talk", "message": problem})
    return []


def _round_draft(state: dict, run_id: str, request: EncounterAct, walk: list[list[int]],
                 judged: judge.JudgeCall | None) -> tuple[dict, dict]:
    """The stranger's part of a round on the latest world (deterministic: safe to redo after model calls)."""
    seen = talk.standing_at(state, walk)
    now = seen["sim_time_ms"]
    current = encounter.active(seen)
    if current is None:
        encounter.open_for_talk(seen, minds.find(seen["npcs"], request.target_id), now)
    elif request.target_id and request.target_id not in current["participants"]:
        encounter.join(seen, minds.find(seen["npcs"], request.target_id), "talk", None, now)
    action = {"kind": request.kind, "text": request.text, "target_id": request.target_id}
    draft, record = encounter.resolve(seen, run_id, action, judged.result if judged else None,
                                      attempts.service_message(judged) if judged else None, request.request_id)
    record["walk"] = walk
    return draft, record


def scene(draft: dict, addressed_id: str, text: str, happened: str | None, allowed: bool,
          nearby: list[dict] | None = None) -> dict:
    """The group's moment (D-48): one voice call, outside the lock. Everyone in the conversation, plus up to
    three people near enough to hear it, may speak in turn, talk to each other or ask the stranger something."""
    current = encounter.active(draft) or {"participants": [addressed_id]}
    addressed = minds.find(draft["npcs"], addressed_id)
    inside = [minds.find(draft["npcs"], n) for n in current["participants"]]
    inside = [n for n in inside if n is not None]
    nearby = [n for n in (talk.bystanders(draft) if nearby is None else nearby)
              if n["id"] not in current["participants"]]
    context = talk.scene_context(draft, addressed, inside, nearby, text, happened)
    call = voice.scene(context, talk.fallback_line(draft, addressed, "answer"), allowed=allowed)
    return {"call": call, "context": context, "addressed": addressed_id,
            "inside": [n["id"] for n in inside], "nearby": [n["id"] for n in nearby]}


def apply_scene(draft: dict, moment: dict, text: str, happened: str | None, now: int) -> list[dict]:
    """Check the scene's lines against the world as it now stands and apply each as that person's exchange.
    Returns what was said: [{npc_id, name, line, kind, key, trace}]. A nearby person who speaks joins first."""
    call, said = moment["call"], []
    lines = call.lines if call.status == "ok" else [
        {"speaker_id": moment["addressed"], "text": call.text, "move": "answer", "answers": {}, "remember": ""}]
    here = minds.player_cell(draft)
    heard = [happened] if happened else []
    for line in lines:
        npc = minds.find(draft["npcs"], line["speaker_id"])
        current = encounter.active(draft)
        if npc is None or current is None or any(s["npc_id"] == npc["id"] for s in said):
            continue  # Not a real person here, the conversation is over, or they've already spoken.
        joining = npc["id"] not in current["participants"]
        if joining and (npc["id"] not in moment["nearby"] or talk.busy(npc)
                        or math.dist(minds._cell(npc), here) > talk.HEAR_TALK_CELLS + 1):
            continue  # Only someone who was really near enough to hear can join in.
        if joining:
            encounter.join(draft, npc, "joined", None, now)
        answers = line.get("answers") or {}
        key = talk.decided_reply(draft, npc, answers, line.get("move") or "answer")
        moment_words = " ".join(heard) or None
        exchange = talk.exchange(draft, npc["id"], text, answers, key, line["text"], [], moment_words,
                                 note=line.get("remember", ""),
                                 name_given=call.stranger_name if npc["id"] == moment["addressed"] else "")
        draft.setdefault("learned", []).extend(exchange["learned"])
        draft["journal"].append(exchange["journal_entry"])
        heard.append(f"{npc['name']} just said: “{line['text']}”")
        said.append({"npc_id": npc["id"], "name": npc["name"], "line": line["text"], "kind": "reply", "key": key,
                     "trace": {"kind": "talk", "npc_id": npc["id"], "text": text, "happened": moment_words,
                               "action": key, "voice_move": line.get("move"), "joined": joining,
                               "why": "addressed" if npc["id"] == moment["addressed"] else "in the scene",
                               "reply": line["text"], "regard_change": exchange["regard_change"],
                               "situation": talk.request(draft, npc, text, moment_words)[0],
                               "call": {"provider": "voice", "model": call.model, "answers": answers},
                               "voice": call.as_dict(), "voice_context": moment["context"]}})
    return said


def play_round(run_id: str, request: EncounterAct, background: BackgroundTasks) -> dict:
    started, timing = time.perf_counter(), {}
    request_json = json.dumps({"kind": request.kind, "text": request.text, "target_id": request.target_id,
                               "selected_ids": request.selected_ids}, sort_keys=True)
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior = connection.execute("SELECT final_seq,request_json FROM action_requests WHERE run_id=? AND request_id=?",
                                   (run_id, request.request_id)).fetchone()
        if prior:
            if prior["request_json"] != request_json:
                raise HTTPException(409, {"reason": "request_id_conflict"})
            replayed = store.state_at(connection, run, prior["final_seq"])
            return {"state": replayed, "duplicate": True, "round": replayed.get("last_round")}
        if connection.execute("SELECT 1 FROM events WHERE run_id=? AND request_id=?",
                              (run_id, request.request_id)).fetchone():
            raise HTTPException(409, {"reason": "request_id_conflict"})
        if store.is_stale(state, request.expected_version):
            raise HTTPException(409, {"reason": "stale_state", "state": state})
        if state["inside_city"] or not state["player"]["alive"]:
            raise HTTPException(409, "Run is no longer interactive")
        walk = _round_setup(state, request)
        if run_id in attempts.busy_runs:
            raise HTTPException(409, {"reason": "in_progress"})
        attempts.busy_runs.add(run_id)
        seen = talk.standing_at(state, walk)
        context = crafting.build_context(seen, request.text, request.selected_ids) if request.kind == "do" else None
        calls_used = telemetry.calls_for_run(connection, run_id)
    try:
        judged = attempts.judge_attempt(context, calls_used) if context else None  # Outside the lock.
        timing["judge_ms"] = judged.latency_ms if judged else 0
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            if store.is_stale(state, request.expected_version):
                raise HTTPException(409, {"reason": "stale_state", "state": state})
            draft, record = _round_draft(state, run_id, request, walk, judged)
            happened = " ".join(record["happened"]) or None
            text = request.text if request.kind == "say" or request.speech else ""
        # The scene answers what actually happened (the person addressed, and anyone who joins in).
        allowed = calls_used < ai_config.max_calls_per_run()
        moment = scene(draft, record["replier"], text, happened, allowed) if record["replier"] else None
        spoken = moment["call"] if moment else None
        timing["scene_ms"] = spoken.latency_ms if spoken else 0
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            if judged and judged.attempts:
                telemetry.record(connection, run_id, "judge", judged.model, judged.prompt_version, judged.latency_ms,
                                 judged.status == "ok", judged.error, judged.input_tokens, judged.output_tokens,
                                 judged.attempts)
            if spoken and spoken.model and spoken.model != "stub":
                telemetry.record(connection, run_id, "voice", spoken.model, spoken.prompt_version, spoken.latency_ms,
                                 spoken.status == "ok", spoken.error, spoken.input_tokens, spoken.output_tokens)
        # Only a real failure changes nothing; stub mode or a spent allowance answers with the authored line.
        broken = spoken is not None and spoken.status != "ok" and bool(spoken.error) \
            and not spoken.error.startswith("Model call allowance")
        if moment and broken and request.kind == "say":
            name = minds.find(draft["npcs"], record["replier"])["name"]
            raise HTTPException(503, {"reason": "decider_failed", "message": (
                f"{name} doesn't seem to hear you. (The model couldn't be reached, so nothing changed.)")})
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            if store.is_stale(state, request.expected_version):
                raise HTTPException(409, {"reason": "stale_state", "state": state})
            walk = _round_setup(state, request)
            draft, record = _round_draft(state, run_id, request, walk, judged)  # Redone on the latest world.
            now = draft["sim_time_ms"]
            said = apply_scene(draft, moment, text, happened, now) if moment and record["replier"] else []
            for line in said:  # Moves the round itself carries out.
                act = line["key"].split(":")[0]
                if act == "seize" and draft["player"].get("alive", True):
                    record["seized_by"] = record.get("seized_by") or line["npc_id"]
                elif act == "attack":
                    combat.start(draft, [line["npc_id"]], now, "attack")
            encounter.finish(draft, record, now, [{k: v for k, v in s.items() if k != "trace"} for s in said])
            elapsed = encounter.round_ms(record)
            people = store.advance_people(draft, elapsed)
            for obj in people.get("objects_added", []):
                draft["objects"][obj["id"]] = dict(obj)
            for object_id, fields in people.get("objects_changed", {}).items():
                draft["objects"][object_id].update(fields)
            draft.update(npcs=people["npcs"], player=people["player"], pending_minds=people["pending_minds"],
                         encounter=people["encounter"], fight=people["fight"], sim_time_ms=now + elapsed,
                         projectiles=people.get("projectiles") or [])
            draft["journal"].extend(people["people_journal"])
            if "barred_until" in people:  # Beaten down and arrested as the round's time passed (D-44).
                draft["barred_until"] = people["barred_until"]
            payload = store.round_payload(state, draft, record)
            payload["safe_seq"] = state["event_seq"] if minds.calm(state) else state.get("safe_seq", 0)
            store.append(connection, state, "round", payload, request.request_id, payload["sim_time_ms"] // 1000)
            store.apply_round(state, payload)
            connection.execute("INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?)",
                               (run_id, request.request_id, state["event_seq"], request_json))
            craft_trace = None
            if record.get("verdict"):
                made = [state["objects"][i] for i in record["entry"].get("made_ids", []) if i in state["objects"]]
                craft_trace = attempts.record_attempt(connection, run_id, request.request_id, state["event_seq"],
                                                      request.text, request.selected_ids, context, judged,
                                                      record["verdict"], made, background)
            for line in said:
                connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                                   (run_id, state["event_seq"], line["npc_id"], json.dumps(line["trace"])))
            round_trace = {"kind": "round", "npc_id": record.get("replier") or "encounter",
                           "why": f"round {record['round']}", "action": request.kind, "entries": record["entries"],
                           "scene": {"inside": moment["inside"], "nearby": moment["nearby"],
                                     "lines": spoken.lines} if moment else None,
                           "timing": dict(timing, total_ms=round((time.perf_counter() - started) * 1000))}
            connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                               (run_id, state["event_seq"], round_trace["npc_id"], json.dumps(round_trace)))
    finally:
        attempts.busy_runs.discard(run_id)
    timing["total_ms"] = round((time.perf_counter() - started) * 1000)
    response = {"state": state, "duplicate": False, "round": state["last_round"], "timing": timing}
    if run["mode"] == "developer":
        response["trace"] = (said[0]["trace"] if said else None) or craft_trace
        response["craft_trace"] = craft_trace
    return response
