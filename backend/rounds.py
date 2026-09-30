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
import re
import time
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

import attempts
import combat
import commands
import crafting
import encounter
import minds
import routes_tutorial
import store
import talk
from ai import config as ai_config
from ai import judge, telemetry, voice

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
    return play_round(
        run_id,
        EncounterAct(
            kind="say",
            text=request.text,
            target_id=request.npc_id,
            expected_version=request.expected_version,
            request_id=request.request_id,
        ),
        background,
    )


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


def _round_draft(
    state: dict, run_id: str, request: EncounterAct, walk: list[list[int]], judged: judge.JudgeCall | None
) -> tuple[dict, dict]:
    """The stranger's part of a round on the latest world (deterministic: safe to redo after model calls)."""
    seen = talk.standing_at(state, walk)
    now = seen["sim_time_ms"]
    current = encounter.active(seen)
    if current is None:
        encounter.open_for_talk(seen, minds.find(seen["npcs"], request.target_id), now)
    elif request.target_id and request.target_id not in current["participants"]:
        encounter.join(seen, minds.find(seen["npcs"], request.target_id), "talk", None, now)
    action = {"kind": request.kind, "text": request.text, "target_id": request.target_id}
    draft, record = encounter.resolve(
        seen,
        run_id,
        action,
        judged.result if judged else None,
        attempts.service_message(judged) if judged else None,
        request.request_id,
    )
    record["walk"] = walk
    return draft, record


def scene(
    draft: dict, addressed_id: str, text: str, happened: str | None, allowed: bool, nearby: list[dict] | None = None
) -> dict:
    """The group's moment (D-48): one voice call, outside the lock. Everyone in the conversation, plus up to
    three people near enough to hear it, may speak in turn, talk to each other or ask the stranger something."""
    current = encounter.active(draft) or {"participants": [addressed_id]}
    addressed = minds.find(draft["npcs"], addressed_id)
    inside = [minds.find(draft["npcs"], n) for n in current["participants"]]
    inside = [n for n in inside if n is not None]
    nearby = [
        n for n in (talk.bystanders(draft) if nearby is None else nearby) if n["id"] not in current["participants"]
    ]
    context = talk.scene_context(draft, addressed, inside, nearby, text, happened)
    call = voice.scene(context, talk.fallback_line(draft, addressed, "answer"), allowed=allowed)
    return {
        "call": call,
        "context": context,
        "addressed": addressed_id,
        "inside": [n["id"] for n in inside],
        "nearby": [n["id"] for n in nearby],
    }


def keep_promise(
    state: dict, npc: dict, promised: str, errand_to: str, errand_message: str
) -> tuple[str, str, str, str | None]:
    """Someone said they'd do something later but the move picked doesn't do it (D-51). If it's an errand to a
    person (named, or "the guards"/"the captain"), they go and do it, with their own words as the message.
    Otherwise it's noted as a promise the game couldn't keep. Returns (key, errand_to, errand_message, unkept)."""
    if "go_tell" in talk.replies(state, npc):
        task = talk.errand(state, npc, errand_to, errand_message or promised)
        if task is None:
            words = set(re.findall(r"[a-z]+", promised.lower()))
            named = next(
                (
                    n
                    for n in state["npcs"]
                    if n["id"] != npc["id"] and n.get("alive", True) and n["name"].split()[0].lower() in words
                ),
                None,
            )
            if named is None and words & {"captain", "guard", "guards", "watch", "gate"}:
                named = minds.find(state["npcs"], talk.CAPTAIN)
            task = talk.errand(state, npc, named["id"], errand_message or promised) if named else None
        if task is not None:
            return "go_tell", task[0]["id"], task[1], None
    return "answer", errand_to, errand_message, promised


def apply_scene(draft: dict, moment: dict, text: str, happened: str | None, now: int) -> list[dict]:
    """Check the scene's lines against the world as it now stands and apply each as that person's exchange.
    Returns what was said: [{npc_id, name, line, kind, key, trace}]. A nearby person who speaks joins first."""
    call, said = moment["call"], []
    lines = (
        call.lines
        if call.status == "ok"
        else [{"speaker_id": moment["addressed"], "text": call.text, "move": "answer", "answers": {}, "remember": ""}]
    )
    here = minds.player_cell(draft)
    heard = [happened] if happened else []
    for line in lines:
        npc = minds.find(draft["npcs"], line["speaker_id"])
        current = encounter.active(draft)
        if npc is None or current is None or any(s["npc_id"] == npc["id"] for s in said):
            continue  # Not a real person here, the conversation is over, or they've already spoken.
        joining = npc["id"] not in current["participants"]
        if joining and (
            npc["id"] not in moment["nearby"]
            or talk.busy(npc)
            or math.dist(minds._cell(npc), here) > talk.HEAR_TALK_CELLS + 1
        ):
            continue  # Only someone who was really near enough to hear can join in.
        if joining:
            encounter.join(draft, npc, "joined", None, now)
        answers = line.get("answers") or {}
        key = talk.decided_reply(draft, npc, answers, line.get("move") or "answer")
        errand_to, errand_message = line.get("errand_to", ""), line.get("errand_message", "")
        promised = line.get("promised_later", "")
        unkept = None
        if promised and key.split(":")[0] not in talk.ERRANDS:  # Said they'd do something: hold them to it (D-51).
            key, errand_to, errand_message, unkept = keep_promise(draft, npc, promised, errand_to, errand_message)
        moment_words = " ".join(heard) or None
        exchange = talk.exchange(
            draft,
            npc["id"],
            text,
            answers,
            key,
            line["text"],
            [],
            moment_words,
            note=line.get("remember", ""),
            name_given=call.stranger_name if npc["id"] == moment["addressed"] else "",
            errand_to=errand_to,
            errand_message=errand_message,
        )
        if unkept:
            exchange["journal_entry"]["unkept_promise"] = unkept
        draft.setdefault("learned", []).extend(exchange["learned"])
        draft["journal"].append(exchange["journal_entry"])
        heard.append(f"{npc['name']} just said: “{line['text']}”")
        said.append(
            {
                "npc_id": npc["id"],
                "name": npc["name"],
                "line": line["text"],
                "kind": "reply",
                "key": key,
                "trace": {
                    "kind": "talk",
                    "npc_id": npc["id"],
                    "text": text,
                    "happened": moment_words,
                    "action": key,
                    "voice_move": line.get("move"),
                    "joined": joining,
                    "why": "addressed" if npc["id"] == moment["addressed"] else "in the scene",
                    "promised_later": promised,
                    "unkept_promise": unkept,
                    "reply": line["text"],
                    "regard_change": exchange["regard_change"],
                    "situation": talk.request(draft, npc, text, moment_words)[0],
                    "call": {"provider": "voice", "model": call.model, "answers": answers},
                    "voice": call.as_dict(),
                    "voice_context": moment["context"],
                },
            }
        )
    return said


def play_round(run_id: str, request: EncounterAct, background: BackgroundTasks) -> dict:
    """One round: the stranger's part (judged if it's a deed), then the scene's answer, then time passing. The two
    model calls happen outside the lock; the round is worked out again on the latest world before it's saved."""
    started, timing = time.perf_counter(), {}
    body = {
        "kind": request.kind,
        "text": request.text,
        "target_id": request.target_id,
        "selected_ids": request.selected_ids,
    }

    def repeated(run, saved: dict, connection) -> dict:
        return {"state": saved, "duplicate": True, "round": saved.get("last_round")}

    try:
        with commands.open(run_id, request, body=body, duplicate=repeated) as cmd:
            walk = _round_setup(cmd.state, request)
            cmd.claim()
            seen = talk.standing_at(cmd.state, walk)
            context = crafting.build_context(seen, request.text, request.selected_ids) if request.kind == "do" else None
            calls_used = telemetry.calls_for_run(cmd.connection, run_id)
    except commands.Reply as reply:
        return reply.body
    try:
        judged = attempts.judge_attempt(context, calls_used) if context else None  # Outside the lock.
        timing["judge_ms"] = judged.latency_ms if judged else 0
        with commands.reopen(run_id, request) as cmd:
            draft, record = _round_draft(cmd.state, run_id, request, walk, judged)
            happened = " ".join(record["happened"]) or None
            text = request.text if request.kind == "say" or request.speech else ""
        # The scene answers what actually happened (the person addressed, and anyone who joins in).
        allowed = calls_used < ai_config.max_calls_per_run()
        moment = scene(draft, record["replier"], text, happened, allowed) if record["replier"] else None
        spoken = moment["call"] if moment else None
        timing["scene_ms"] = spoken.latency_ms if spoken else 0
        with store.lock, store.db() as connection:
            if judged and judged.attempts:
                telemetry.log(connection, run_id, "judge", judged)
            if spoken and spoken.model and spoken.model != "stub":
                telemetry.log(connection, run_id, "voice", spoken)
        # Only a real failure changes nothing; stub mode or a spent allowance answers with the authored line.
        broken = (
            spoken is not None
            and spoken.status != "ok"
            and bool(spoken.error)
            and not spoken.error.startswith("Model call allowance")
        )
        if moment and broken and request.kind == "say":
            name = minds.find(draft["npcs"], record["replier"])["name"]
            raise HTTPException(
                503,
                {
                    "reason": "decider_failed",
                    "message": (
                        f"{name} doesn't seem to hear you. (The model couldn't be reached, so nothing changed.)"
                    ),
                },
            )
        with commands.reopen(run_id, request, body=body) as cmd:
            state = cmd.state
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
            _pass_round_time(draft, now, encounter.round_ms(record))
            _adopt_round(state, draft, record, state["event_seq"] if minds.calm(state) else state.get("safe_seq", 0))
            cmd.save("round")
            craft_trace = _traces(
                cmd, request, context, judged, record, said, moment, spoken, timing, started, background
            )
    finally:
        commands.release(run_id)
    routes_tutorial.after_action(state)  # The tutorial may move on (D-50).
    timing["total_ms"] = round((time.perf_counter() - started) * 1000)
    response = {"state": state, "duplicate": False, "round": state["last_round"], "timing": timing}
    if cmd.developer:
        response["trace"] = (said[0]["trace"] if said else None) or craft_trace
        response["craft_trace"] = craft_trace
    return response


# What a round may change (anything a Try Something can, a reply, people moving on): taken from its worked-out copy.
ROUND_FIELDS = (
    "objects",
    "npcs",
    "player",
    "encounter",
    "fight",
    "pending_minds",
    "agreements",
    "sim_time_ms",
    "water_spilled_l",
    "last_action",
    "gate_open",
    "barred_until",
    "trades",
    "projectiles",
)


def _adopt_round(state: dict, draft: dict, record: dict, safe_seq: int) -> None:
    """The round as worked out on the draft becomes the world: its fields, what was said and learned, an admission."""
    journal_before, learned_before = len(state["journal"]), len(state.get("learned", []))
    admitted_now = draft.get("admitted") and not state.get("admitted")
    for key in ROUND_FIELDS:
        state[key] = draft.get(key)
    state["trades"] = draft.get("trades") or {}
    state["journal"].extend(draft["journal"][journal_before:])
    state.setdefault("learned", []).extend(draft.get("learned", [])[learned_before:])
    if admitted_now:
        state["admitted"] = draft["admitted"]
    state["safe_seq"] = safe_seq
    state["last_round"] = {
        key: record.get(key)
        for key in ("round", "entries", "ended", "walked_away", "replier", "effort_seconds", "walk", "arrested")
    }


def _pass_round_time(draft: dict, now: int, elapsed: int) -> None:
    """The round takes time: everyone's day moves on by that much in the draft (routines, jobs, blows landing)."""
    people = store.advance_people(draft, elapsed)
    for obj in people.get("objects_added", []):
        draft["objects"][obj["id"]] = dict(obj)
    for object_id, fields in people.get("objects_changed", {}).items():
        draft["objects"][object_id].update(fields)
    draft.update(
        npcs=people["npcs"],
        player=people["player"],
        pending_minds=people["pending_minds"],
        encounter=people["encounter"],
        fight=people["fight"],
        sim_time_ms=now + elapsed,
        projectiles=people.get("projectiles") or [],
    )
    draft["journal"].extend(people["people_journal"])
    if "barred_until" in people:  # Beaten down and arrested as the round's time passed (D-44).
        draft["barred_until"] = people["barred_until"]


def _traces(cmd, request, context, judged, record, said, moment, spoken, timing, started, background) -> dict | None:
    """The developer's view of the round: the judged deed (if any), each line's thinking, and the round itself."""
    state, connection, run_id = cmd.state, cmd.connection, cmd.run_id
    craft_trace = None
    if record.get("verdict"):
        made = [state["objects"][i] for i in record["entry"].get("made_ids", []) if i in state["objects"]]
        craft_trace = attempts.record_attempt(
            connection,
            run_id,
            request.request_id,
            state["event_seq"],
            request.text,
            request.selected_ids,
            context,
            judged,
            record["verdict"],
            made,
            background,
        )
    for line in said:
        connection.execute(
            "INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
            (run_id, state["event_seq"], line["npc_id"], json.dumps(line["trace"])),
        )
    round_trace = {
        "kind": "round",
        "npc_id": record.get("replier") or "encounter",
        "why": f"round {record['round']}",
        "action": request.kind,
        "entries": record["entries"],
        "scene": {"inside": moment["inside"], "nearby": moment["nearby"], "lines": spoken.lines} if moment else None,
        "timing": dict(timing, total_ms=round((time.perf_counter() - started) * 1000)),
    }
    connection.execute(
        "INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
        (run_id, state["event_seq"], round_trace["npc_id"], json.dumps(round_trace)),
    )
    return craft_trace
