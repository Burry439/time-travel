"""Deals, vouching, the guards' halt and Roderic's admission, with a scripted decider, judge and voice."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as service
import crafting
import minds
import talk
import village
from ai import decider, voice
from test_craft import attempt, judged
from test_talk import npc, said, unit_state, walk_to

@pytest.fixture(autouse=True)
def quiet_village(monkeypatch):
    """These tests follow reactions to the stranger step by step; the village's own life (agendas, meetings)
    is tested in test_village.py."""
    monkeypatch.setattr(village, "schedule", lambda state, npcs, now: None)



def answers(reply, **yes):
    out = said(reply)
    out.update({name: {"type": "noul", "noul": value} for name, value in yes.items()})
    return out


def test_any_guard_with_their_own_reasons_admits_but_never_after_a_crime():
    state = unit_state()
    roderic, bren = npc(state, "npc_roderic_vale"), npc(state, "npc_bren_marr")
    assert "admit" in talk.replies(state, roderic) and "admit" in talk.replies(state, bren)  # D-43.
    assert "admit" not in talk.replies(state, npc(state, "npc_hessa_marr"))  # Not a guard: not hers to give.
    bren["down"] = True
    assert "admit" not in talk.replies(state, bren)
    minds.remember(roderic, {"kind": "violence", "severity": 2, "event": 3, "summary": "The stranger attacked Oren.",
                             "short": "attacked Oren", "victim": "npc_oren_dast", "source": "witnessed"})
    assert "admit" not in talk.replies(state, roderic)
    roderic["mind"]["memories"][-1]["doubted"] = True  # He doesn't believe it.
    assert "admit" in talk.replies(state, roderic)


def test_offers_come_from_authored_needs_and_vouching_needs_trust():
    state = unit_state()
    tomas = npc(state, "npc_tomas_reed")
    options = talk.replies(state, tomas)
    assert "offer:beam_help" in options and "gate beam" in options["offer:beam_help"]["description"]
    assert "vouch" not in options
    talk.regard(tomas)["trust"] = 0.65
    assert "vouch" in talk.replies(state, tomas)
    assert "vouch" not in talk.replies(state, npc(state, "npc_roderic_vale"))  # He is who they vouch to.


def test_a_deal_is_offered_accepted_done_and_rewarded_once():
    state = unit_state()
    state["player"].update(x=40, y=40)
    npc(state, "npc_tomas_reed").update(x=41, y=40)
    talk.exchange(state, "npc_tomas_reed", "Any work going?", answers("offer:beam_help"), "offer:beam_help",
                  "Help me with that beam and I'll speak for you.", [])
    (deal,) = state["agreements"].values()
    assert deal["status"] == "proposed" and deal["issuer"] == "npc_tomas_reed"
    assert "offer:beam_help" not in talk.replies(state, npc(state, "npc_tomas_reed"))  # Offered once.
    situation, questions = talk.request(state, npc(state, "npc_tomas_reed"), "Deal.")
    assert "accepts" in questions and "offered, not yet agreed" in situation
    state["event_seq"] += 1
    talk.exchange(state, "npc_tomas_reed", "Deal.", answers("answer", accepts=0.9), "answer", "Good.", [])
    assert deal["status"] == "accepted"
    _, questions = talk.request(state, npc(state, "npc_tomas_reed"), "It's done.")
    assert "done" not in questions  # The beam isn't up yet: no words can make it done.
    state["objects"]["gate_beam"]["installed_in"] = "gate_brackets"
    _, questions = talk.request(state, npc(state, "npc_tomas_reed"), "It's done.")
    assert "done" in questions and "never from the stranger's word" in questions["done"]["instructions"]
    state["event_seq"] += 1
    talk.exchange(state, "npc_tomas_reed", "Trust me, it's done.", answers("answer", done=0.2), "answer", "Is it?", [])
    assert deal["status"] == "accepted"  # Not convinced: nothing happens.
    state["event_seq"] += 1
    talk.exchange(state, "npc_tomas_reed", "There.", answers("answer", done=0.9), "answer", "Well I never.", [])
    tomas = npc(state, "npc_tomas_reed")
    assert deal["status"] == "fulfilled" and tomas["mind"]["job"]["kind"] == "vouch" and tomas["mind"]["vouched"]
    state["event_seq"] += 1
    talk.exchange(state, "npc_tomas_reed", "There.", answers("answer", done=0.9), "answer", "Yes, yes.", [])
    assert sum(1 for a in state["agreements"].values() if a["status"] == "fulfilled") == 1  # Rewarded once.


def run(state, done, limit_ms=90_000, beat=500):
    for _ in range(limit_ms // beat):
        state["npcs"], heard, state["player"] = minds.advance_world(state, beat, state["sim_time_ms"])
        state["sim_time_ms"] += beat
        state.setdefault("heard", []).extend(heard)
        if done():
            return True
    return False


def test_a_vouch_walks_to_the_captain_and_becomes_his_evidence():
    state = unit_state()
    tomas = npc(state, "npc_tomas_reed")
    talk.speak_for(state, tomas, "they did what I asked.", "Tomas vouched for the stranger.", 7, 0)
    assert run(state, lambda: any(m["kind"] == "vouch" for m in minds.mind(npc(state, "npc_roderic_vale"))["memories"]))
    memory = npc(state, "npc_roderic_vale")["mind"]["memories"][-1]
    assert memory["by"] == "npc_tomas_reed" and memory["source"] == "told_by:npc_tomas_reed"
    assert not state["pending_minds"]  # He weighs it when the stranger comes to him.


def test_guards_halt_a_stranger_at_the_gate_but_not_once_admitted():
    state = unit_state()
    state["player"].update(x=48, y=16)
    assert run(state, lambda: any(e.get("category") == "halt" for e in state["heard"]), limit_ms=30_000)
    halt = next(e for e in state["heard"] if e["category"] == "halt")
    assert minds.card(npc(state, halt["npc_id"]))["guard"]
    state["heard"].clear()
    assert not run(state, lambda: any(e.get("category") == "halt" for e in state["heard"]), limit_ms=20_000)
    admitted = unit_state()
    admitted["player"].update(x=48, y=16)
    admitted["admitted"] = {"by": "npc_roderic_vale"}
    assert not run(admitted, lambda: any(e.get("category") == "halt" for e in admitted.get("heard", [])),
                   limit_ms=20_000)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(service.store, "DB_PATH", tmp_path / "gate.sqlite3")
    monkeypatch.setattr(service.attempts, "ASSET_DIR", tmp_path / "assets")
    script, rulings, moves = [], [], []

    def fake_decide(situation, questions):
        if "impression" not in questions:  # People choosing what to do (not answering the stranger): they stay and listen.
            return decider.DeciderCall(provider="script", model="script", answers={
                k: {"type": "choice", "choice": "listen"} for k in questions if k.endswith("action")})
        return decider.DeciderCall(provider="script", model="script", error="talk is the voice's now (D-46)")
    monkeypatch.setattr(service.decider, "decide", fake_decide)
    monkeypatch.setattr(service.decider, "decide_many", lambda requests: [fake_decide(*r) for r in requests])
    def fake_voice(context, fallback, allowed=True):  # The scripted reply: the voice's move and reading (D-46).
        reply = script.pop(0) if script else {}
        return voice.VoiceCall(status="ok", text=fallback, model="fake", answers=reply,
                               move=reply.get("reply", {}).get("choice", "answer"))
    monkeypatch.setattr(service.voice, "converse", fake_voice)
    monkeypatch.setattr(service.judge, "judge_craft", lambda context: service.judge.JudgeCall(
        status="ok", result=rulings.pop(0), model="stub", attempts=1))
    monkeypatch.setattr(service.attempts, "_generate_asset", lambda asset_id: None)
    return SimpleNamespace(http=TestClient(service.app), script=script, rulings=rulings)


def walk(http, state, x, y):
    """Walk around buildings (the gate rows count as open once the gate is)."""
    start = (state["player"]["x"], state["player"]["y"])
    previous, steps = crafting._bfs(start, crafting._blocked_cells(state), 200)
    goal = min(steps, key=lambda c: (abs(c[0] - x) + abs(c[1] - max(y, 9)), steps[c]))
    path = []
    while goal != start:
        path.append(list(goal))
        goal = previous[goal]
    path = path[::-1] + [[x, row] for row in range(8, y - 1, -1)] if y < 9 else path[::-1]
    for i in range(0, len(path), 20):
        reply = http.post(f"/runs/{state['run_id']}/move", json={
            "cells": path[i:i + 20], "expected_version": state["event_seq"], "request_id": f"walk-{state['event_seq']}"})
        assert reply.status_code == 200, reply.text
        state = reply.json()["state"]
    return state


def say(world, state, npc_id, text, reply):
    world.script.append(reply)
    response = world.http.post(f"/runs/{state['run_id']}/say", json={
        "npc_id": npc_id, "text": text, "expected_version": state["event_seq"], "request_id": f"say-{state['event_seq']}"})
    assert response.status_code == 200, response.text
    return response.json()["state"]


def settle(world, state, until, limit=200):
    """Let the clock run (and anyone thinking carry on) until the condition holds."""
    for _ in range(limit):
        if until(state):
            return state
        if state.get("pending_minds"):
            reply = world.http.post(f"/runs/{state['run_id']}/think", json={
                "expected_version": state["event_seq"], "request_id": f"think-{state['event_seq']}"})
        else:
            reply = world.http.post(f"/runs/{state['run_id']}/explore", json={
                "elapsed_ms": 1000, "expected_version": state["event_seq"], "request_id": f"beat-{state['event_seq']}"})
        assert reply.status_code == 200, reply.text
        state = reply.json()["state"]
    raise AssertionError("condition never held")


def test_bringing_hessa_water_earns_her_word_and_the_captain_lets_you_in(world):
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 52)  # By the gourd (45, 53).
    world.rulings.append(attempt(judged("take", take_ids=["gourd_a"]), key="take"))
    state = http.post(f"/runs/{state['run_id']}/craft", json={
        "text": "take the gourd", "selected_ids": ["gourd_a"], "expected_version": state["event_seq"],
        "request_id": "take-gourd"}).json()["state"]
    state = walk_to(http, state, 36, 53)  # Beside Hessa and her trough.
    state = say(world, state, "npc_hessa_marr", "Any way I can help?", answers("offer:water_haul"))
    state = say(world, state, "npc_hessa_marr", "Gladly, I'll fetch it.", answers("answer", accepts=0.95))
    assert next(iter(state["agreements"].values()))["status"] == "accepted"
    world.rulings.append(attempt(
        judged("fill", fill={"container_id": "gourd_a", "source_id": "trough_hessa", "litres": 1.0}),
        judged("give", give={"item_ids": ["gourd_a"], "recipient_id": "npc_hessa_marr"}), key="fill+give"))
    state = http.post(f"/runs/{state['run_id']}/craft", json={
        "text": "fill the gourd at the trough and give it to Hessa", "selected_ids": [],
        "expected_version": state["event_seq"], "request_id": "water"}).json()["state"]
    assert state["objects"]["gourd_a"]["holder_id"] == "npc_hessa_marr"
    hessa = npc(state, "npc_hessa_marr")
    assert "with 1 L of water in it" in minds.worst_memory(hessa)["summary"] or \
        any("water" in m["summary"] for m in hessa["mind"]["memories"] if m["kind"] == "gift")
    state = settle(world, state, lambda s: not s.get("pending_minds"))
    state = say(world, state, "npc_hessa_marr", "Here's your water.", answers("answer", done=0.9))
    assert npc(state, "npc_hessa_marr")["mind"]["job"]["kind"] == "vouch"
    state = settle(world, state, lambda s: any(m["kind"] == "vouch" for m in minds.mind(
        npc(s, "npc_roderic_vale"))["memories"]))
    roderic = npc(state, "npc_roderic_vale")
    state = walk(http, state, roderic["x"], roderic["y"] + 2)
    state = say(world, state, "npc_roderic_vale", "Hessa has spoken for me. May I enter?",
                answers("admit", reason=0.8, threat=0.1))
    assert state["gate_open"] and state["admitted"]["by"] == "npc_roderic_vale"
    assert any("Hessa vouched" in reason for reason in state["admitted"]["because"])
    state = walk(http, state, 48, 3)
    assert state["inside_city"]
    assert http.get(f"/runs/{state['run_id']}").json() == state  # The whole route replays exactly.


def test_business_and_demonstrated_value_are_routes_too():
    state = unit_state()
    state["player"].update(x=79, y=31)
    darin = npc(state, "npc_darin_ko")
    darin.update(x=80, y=31)
    talk.exchange(state, "npc_darin_ko", "What would you pay for something new?", answers("offer:trade_goods"),
                  "offer:trade_goods", "Show me something I can sell.", [])
    state["event_seq"] += 1
    talk.exchange(state, "npc_darin_ko", "Agreed.", answers("answer", accepts=0.9), "answer", "Good.", [])
    state["event_seq"] += 1
    talk.exchange(state, "npc_darin_ko", "Like that?", answers("answer", done=0.95), "answer", "Oh, yes.", [])
    job = npc(state, "npc_darin_ko")["mind"]["job"]
    assert job["kind"] == "vouch" and "hired the stranger" in job["summary"] and "permit" in job["summary"]
    # Value: the captain saw something useful with his own eyes, and says why he let the stranger in.
    roderic = npc(state, "npc_roderic_vale")
    state["player"].update(x=48, y=13)
    minds.remember(roderic, {"kind": "demonstration", "severity": 1, "event": 40, "clarity": "clear", "works": True,
                             "summary": "The stranger's floating needle kept pointing the same way in the fog.",
                             "short": "showed off a water compass", "victim": None, "source": "shown"})
    state["event_seq"] += 1
    payload = talk.exchange(state, "npc_roderic_vale", "It will guide your patrols.", answers("admit"), "admit",
                            "Open the gate.", [])
    assert state["gate_open"] and payload["admission"]["because"] == [
        "The stranger's floating needle kept pointing the same way in the fog."]


def test_lent_things_can_be_used_without_theft():
    state = unit_state()
    state["player"].update(x=79, y=32)
    darin = npc(state, "npc_darin_ko")
    assert "lend:lodestone_darin" in talk.replies(state, darin)
    talk.exchange(state, "npc_darin_ko", "May I borrow your odd stone?", answers("lend:lodestone_darin"),
                  "lend:lodestone_darin", "Take it. Carefully.", [])
    stone = state["objects"]["lodestone_darin"]
    assert stone["lent_to"] == "player" and stone["owner_id"] == "npc_darin_ko"
    assert "lend:lodestone_darin" not in talk.replies(state, npc(state, "npc_darin_ko"))
    taken = crafting.validate(state, judged("take", take_ids=["lodestone_darin"]))
    assert taken["category"] == "success" and taken["property"] == []  # Not recorded as theft.
    other = crafting.validate(state, judged("take", take_ids=["cloth_darin"]))
    assert other["property"][0]["how"] == "taken"  # Everything else of his still is.


def test_the_captain_admits_when_he_believes_his_own_rule_is_met():
    state = unit_state()
    roderic = npc(state, "npc_roderic_vale")
    state["player"].update(x=roderic["x"], y=roderic["y"] + 1)
    _, questions = talk.request(state, roderic, "May I enter?")
    assert {"threat", "reason"} <= set(questions)
    # Letting someone in is a move the voice may choose, and code allows it only when the beliefs agree (D-44).
    assert talk.decided_reply(state, roderic, answers("admit", reason=0.8, threat=0.2), "admit") == "admit"
    assert talk.decided_reply(state, roderic, answers("admit", reason=0.8, threat=0.7), "admit") == "answer"
    assert talk.decided_reply(state, roderic, answers("admit", reason=0.3, threat=0.1), "admit") == "answer"
    # Beliefs alone never open the gate on words that refuse.
    assert talk.decided_reply(state, roderic, answers("x", reason=0.9, threat=0.1), "tell_to_leave") == "tell_to_leave"
    _, questions = talk.request(state, npc(state, "npc_bren_marr"), "May I enter?")
    assert "Hessa has vouched" in questions["reason"]["instructions"]  # Bren weighs it by his own lights.
    _, questions = talk.request(state, npc(state, "npc_hessa_marr"), "May I enter?")
    assert "reason" not in questions
