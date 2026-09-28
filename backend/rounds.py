"""Talking and encounter rounds: the stranger's part of a round, everyone's intents, replies.

/say and /encounter/act both play one round (encounter.py has the rules); the decider and the voice
run outside the lock and the round is redone on the latest world before it is committed as one event.
"""
from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

import attempts
import crafting
import encounter
import minds
import store
import talk
from ai import config as ai_config, decider, judge, telemetry, voice

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
    """The stranger's part of a round: say, do, wait or walk away. Everyone's actions resolve together."""
    return play_round(run_id, request, background)


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
                                      attempts.service_message(judged) if judged else None, request.request_id)
    record["walk"] = walk
    return draft, record


def _speak(draft: dict, npc: dict, text: str, happened: str | None, ask: tuple[str, dict], run_id: str,
           allowed: bool) -> dict:
    """One person's reply in a round: Jev decides what they do, the voice says it (outside the lock)."""
    decided = decider.decide(*ask)
    out = {"decided": decided, "ask": ask, "happened": happened, "key": None, "context": None, "spoken": None}
    if decided.ok:
        out["key"] = talk.decided_reply(draft, npc, decided.answers, ask[1])
        out["context"] = talk.voice_context(draft, npc, text, out["key"], decided.answers, happened)
        out["spoken"] = voice.speak(out["context"], talk.fallback_line(draft, npc, out["key"]), allowed=allowed)
    return out


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
        missing = encounter.missing_intents(seen)
        asking = encounter.intent_request(seen, missing) if missing else None
        context = crafting.build_context(seen, request.text, request.selected_ids) if request.kind == "do" else None
        calls_used = telemetry.calls_for_run(connection, run_id)
    try:
        # Everyone's intent for this round (usually decided already while the player typed) and the judge
        # for the stranger's attempt: both outside the lock, side by side.
        with ThreadPoolExecutor(max_workers=2) as pool:
            intent_job = pool.submit(decider.decide, asking[0], asking[1]) if asking else None
            judge_job = pool.submit(attempts.judge_attempt, context, calls_used) if context else None
            intent_call = intent_job.result() if intent_job else None
            judged = judge_job.result() if judge_job else None
        timing["intents_ms"] = intent_call.latency_ms if intent_call else 0
        timing["judge_ms"] = judged.latency_ms if judged else 0
        intents = {n: minds.answers_for(intent_call.answers, asking[2][n]) for n in missing} \
            if intent_call and intent_call.ok else {}
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            if store.is_stale(state, request.expected_version):
                raise HTTPException(409, {"reason": "stale_state", "state": state})
            draft, record = _round_draft(state, run_id, request, walk, intents, judged)
            replier = minds.find(draft["npcs"], record["replier"]) if record["replier"] else None
            happened = " ".join(record["happened"]) or None
            text = request.text if request.kind == "say" or request.speech else ""
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
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
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
                e["kind"] in ("attack", "flee", "leave", "shout_for_help", "whistle") for e in record["entries"]):
            raise HTTPException(503, {"reason": "decider_failed", "message": (
                f"{replier['name']} doesn't seem to hear you. (The decider couldn't be reached, so nothing changed.)")})
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            if store.is_stale(state, request.expected_version):
                raise HTTPException(409, {"reason": "stale_state", "state": state})
            walk = _round_setup(state, request)
            draft, record = _round_draft(state, run_id, request, walk, intents, judged)  # Redone on the latest world.
            now, replies, talk_trace = draft["sim_time_ms"], [], None
            for spoke, person, words, kind in ((main, replier, text, "reply"), (side, cutting_in, "", "interject")):
                if not (spoke and spoke["spoken"]) or record["replier" if kind == "reply" else "interjector"] \
                        != person["id"]:
                    continue
                said = talk.exchange(draft, person["id"], words, spoke["decided"].answers, spoke["key"],
                                     spoke["spoken"].text, [], spoke["happened"], note=spoke["spoken"].remember,
                                     name_given=spoke["spoken"].stranger_name)
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
            people = store.advance_people(draft, elapsed)
            for object_id, fields in people.get("objects_changed", {}).items():
                draft["objects"][object_id].update(fields)
            draft.update(npcs=people["npcs"], player=people["player"], pending_minds=people["pending_minds"],
                         encounter=people["encounter"], fight=people["fight"], sim_time_ms=now + elapsed)
            draft["journal"].extend(people["people_journal"])
            payload = store.round_payload(state, draft, record)
            payload["safe_seq"] = state["event_seq"] if minds.calm(state) else state.get("safe_seq", 0)
            store.append(connection, state, "round", payload, request.request_id, payload["sim_time_ms"] // 1000)
            store.apply_round(state, payload)
            connection.execute("INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?)",
                               (run_id, request.request_id, state["event_seq"], request_json))
            craft_trace = None
            if record.get("verdict"):
                made = [state["objects"][i] for i in record["entry"].get("made_ids", []) if i in state["objects"]]
                craft_trace = attempts.record_attempt(connection, run_id, request.request_id, state["event_seq"], request.text,
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
        attempts.busy_runs.discard(run_id)
    timing["total_ms"] = round((time.perf_counter() - started) * 1000)
    response = {"state": state, "duplicate": False, "round": state["last_round"], "timing": timing}
    if run["mode"] == "developer":
        response["trace"] = talk_trace or craft_trace
        response["craft_trace"] = craft_trace
    return response
