"""Encounters: simultaneous rounds with the people who address the stranger (scripted decider, judge and voice)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as service
import encounter
import minds
from ai import decider, voice
from test_craft import attempt, judged
from test_talk import npc, said, unit_state


def face_to_face(state, npc_id, intent="listen", reason="confront"):
    """The stranger beside someone who has come to address them."""
    person = npc(state, npc_id)
    state["player"].update(x=person["x"], y=person["y"] + 1)
    encounter.join(state, person, reason, "You there!", state["sim_time_ms"])
    state["encounter"]["intents"][npc_id] = {"action": intent, "line": None, "line_id": None}
    return person


def blow(target, result="wounded", weapon=None, effort=2):
    return attempt(judged("harm", effort_seconds=effort, harm={
        "target_id": target, "weapon_id": weapon, "method": "melee", "result": result, "injury": "a hard blow"}))


def play(state, kind, text="", judged_result=None, target=None):
    state["event_seq"] += 1
    return encounter.resolve(state, "enc00000", {"kind": kind, "text": text, "target_id": target}, judged_result,
                             None, "trace")


def test_people_who_come_to_address_the_stranger_open_an_encounter():
    state = unit_state()
    state["player"].update(x=48, y=16)  # The gate approach: a guard comes to halt the stranger.
    for _ in range(80):
        state["npcs"], _, state["player"] = minds.advance_world(state, 500, state["sim_time_ms"])
        state["sim_time_ms"] += 500
        if state.get("encounter"):
            break
    current = state["encounter"]
    guard = npc(state, current["participants"][0])
    assert current["reason"] == "halt" and minds.card(guard)["guard"] and encounter.hostile(state)
    assert current["intents"][guard["id"]]["action"] == "listen" and guard["mind"]["job"]["kind"] == "encounter"
    assert current["log"][0]["text"].startswith(guard["name"] + ": “")
    where = (guard["x"], guard["y"])
    state["npcs"], _, _ = minds.advance_world(state, 5_000, state["sim_time_ms"])
    assert (npc(state, guard["id"])["x"], npc(state, guard["id"])["y"]) == where  # Holds still, face to face.


def test_both_act_at_once_a_blow_lands_while_they_are_talking():
    state = unit_state()
    face_to_face(state, "npc_bren_marr", intent="listen")
    draft, record = play(state, "do", "punch Bren", blow("npc_bren_marr"))
    bren = npc(draft, "npc_bren_marr")
    assert bren["health"] < 100 and bren["alive"]
    assert record["replier"] == "npc_bren_marr"  # He was listening, so he answers what just happened...
    assert "Bren" in " ".join(record["happened"])  # ...which is the blow he just took.
    assert [e["kind"] for e in record["entries"]] == ["do"]


def rounds_where(state, first):
    """Round numbers in which the initiative roll puts `first` ahead."""
    found = []
    for number in range(1, 60):
        state["encounter"]["round"] = number
        if encounter._initiative(state, state["encounter"], "enc00000")[0] == first:
            found.append(number)
    return found


def test_initiative_decides_what_a_killing_blow_prevents():
    state = unit_state()
    face_to_face(state, "npc_mara_venn", intent="attack", reason="attack")
    state["encounter"]["round"] = rounds_where(state, "player")[0]
    draft, record = play(state, "do", "stab Mara", blow("npc_mara_venn", "killed"))
    assert not npc(draft, "npc_mara_venn")["alive"] and draft["player"].get("health", 100) == 100
    assert not any(e["kind"] == "strike" for e in record["entries"])  # Dead before she could swing.
    state = unit_state()
    face_to_face(state, "npc_mara_venn", intent="attack", reason="attack")
    state["encounter"]["round"] = rounds_where(state, "npc_mara_venn")[0]
    draft, record = play(state, "do", "stab Mara", blow("npc_mara_venn", "killed"))
    assert [e["kind"] for e in record["entries"]][:1] == ["strike"]  # She swung first; then his blow landed too.
    assert not npc(draft, "npc_mara_venn")["alive"] or not draft["player"]["alive"]
    again, again_record = play(state, "do", "stab Mara", blow("npc_mara_venn", "killed"))
    assert again_record["entries"] == record["entries"][:len(again_record["entries"])]  # Seeded: repeatable.


def test_a_long_action_mid_fight_costs_extra_blows(monkeypatch):
    monkeypatch.setitem(minds.WEAPONS, "spear", {"hit": 1.0, "damage": 1, "kill": 0.0})  # Survive to count them.
    state = unit_state()
    face_to_face(state, "npc_bren_marr", intent="attack", reason="attack")
    spear = attempt(judged("make", effort_seconds=12, new_object={
        "name": "crude spear", "description": "A stick.", "materials": ["wood"], "consumes": ["branch_a"],
        "tools_used": [], "mass_kg": 1.0, "length_m": 1.5, "capacity_l": None, "rated_load_kg": None,
        "flags": ["rigid"], "capabilities": []}))
    state["objects"]["branch_a"]["holder_id"] = "player"
    _, record = play(state, "do", "make a spear", spear)
    strikes = [e for e in record["entries"] if e["kind"] == "strike"]
    assert len(strikes) == 1 + (12_000 - encounter.ROUND_MS) // minds.ATTACK_INTERVAL_MS
    assert any("while you were busy" in e["text"] for e in strikes)


def test_walking_away_ends_it_but_an_attacker_gets_a_swing_and_gives_chase():
    state = unit_state()
    face_to_face(state, "npc_bren_marr", intent="attack", reason="attack")
    draft, record = play(state, "leave")
    assert any(e["kind"] == "strike" for e in record["entries"]) and record["replier"] is None
    encounter.finish(draft, record, draft["sim_time_ms"])
    assert draft["encounter"] is None and record["ended"]
    job = npc(draft, "npc_bren_marr")["mind"]["job"]
    assert job["kind"] == "attack" and job["wait_until"] > draft["sim_time_ms"]
    calm = unit_state()
    face_to_face(calm, "npc_hessa_marr", intent="listen", reason="talk")
    draft, record = play(calm, "leave")
    encounter.finish(draft, record, draft["sim_time_ms"])
    assert draft["encounter"] is None and npc(draft, "npc_hessa_marr")["mind"]["job"]["kind"] != "attack"


def test_someone_who_walks_up_mid_encounter_joins_it():
    state = unit_state()
    face_to_face(state, "npc_hessa_marr", intent="listen", reason="talk")
    bren = npc(state, "npc_bren_marr")
    bren.update(x=state["player"]["x"] + 6, y=state["player"]["y"])
    minds._set_job(bren, {"kind": "approach", "target": "player", "stop": 2.0, "speed": "walk", "then": "confront",
                          "line": "What's going on here?", "line_id": None}, 0)
    state["npcs"], _, _ = minds.advance_world(state, encounter.ROUND_MS, state["sim_time_ms"])
    assert state["encounter"]["participants"] == ["npc_hessa_marr", "npc_bren_marr"]
    assert state["encounter"]["reason"] == "confront"  # No longer just a chat.


def test_intents_come_from_code_and_turning_on_the_stranger_makes_it_a_fight():
    state = unit_state()
    person = face_to_face(state, "npc_hessa_marr", reason="talk")
    options = encounter.intent_options(state, person)
    assert {o["action"] for o in options.values()} == {"listen", "attack", "shout_for_help", "flee", "leave"}
    guard = face_to_face(state, "npc_bren_marr", reason="halt")
    assert "whistle" in {o["action"] for o in encounter.intent_options(state, guard).values()}
    state["encounter"]["reason"] = "talk"
    encounter.set_intent(state, person, {"action": {"choice": next(k for k in options if k.startswith("attack"))}})
    assert state["encounter"]["intents"]["npc_hessa_marr"]["action"] == "attack" and encounter.hostile(state)


# --- Over HTTP ----------------------------------------------------------------------------------------

@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "enc.sqlite3")
    monkeypatch.setattr(service, "ASSET_DIR", tmp_path / "assets")
    replies, intents, rulings = [], [], []

    def fake_decide(situation, questions):
        if "reply" in questions:
            return decider.DeciderCall(provider="script", model="script", answers=replies.pop(0) if replies else {})
        choice = intents.pop(0) if intents else "listen"
        return decider.DeciderCall(provider="script", model="script", answers={
            k: {"type": "choice", "choice": choice} for k in questions if k.endswith("action")})
    monkeypatch.setattr(service.decider, "decide", fake_decide)
    monkeypatch.setattr(service.decider, "decide_many", lambda requests: [fake_decide(*r) for r in requests])
    monkeypatch.setattr(service.voice, "speak", lambda context, fallback, allowed=True: voice.VoiceCall(
        status="ok", text=f"(voiced) {context['what_just_happened'] or context['stranger_says']}"[:120], model="fake"))
    monkeypatch.setattr(service.judge, "judge_craft", lambda context: service.judge.JudgeCall(
        status="ok", result=rulings.pop(0), model="stub", attempts=1))
    monkeypatch.setattr(service, "_generate_asset", lambda asset_id: None)
    return SimpleNamespace(http=TestClient(service.app), replies=replies, intents=intents, rulings=rulings)


def post(world, state, path, body, status=200):
    reply = world.http.post(f"/runs/{state['run_id']}/{path}", json={
        **body, "expected_version": state["event_seq"], "request_id": f"{path}-{state['event_seq']}"})
    assert reply.status_code == status, reply.text
    return reply.json()


def test_a_halt_becomes_rounds_that_replay_and_walking_away_ends_it(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    cells = [[48, y] for y in range(67, 15, -1)]
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i:i + 20]})["state"]
    for _ in range(60):
        if state.get("encounter"):
            break
        state = post(world, state, "explore", {"elapsed_ms": 1000})["state"]
    guard = state["encounter"]["participants"][0]
    assert post(world, state, "explore", {"elapsed_ms": 1000}, status=409)["detail"]["reason"] == "encounter_active"
    world.replies.append(said("ask_back"))
    body = post(world, state, "encounter/act", {"kind": "say", "text": "Just a traveller, looking for work."})
    state = body["state"]
    assert body["round"]["replier"] == guard and state["encounter"]["round"] == 2
    assert [e["kind"] for e in body["round"]["entries"]] == ["say", "reply"]
    assert body["trace"]["kind"] == "talk" and any(p["kind"] == "round" for p in state["pending_minds"])
    assert world.http.get(f"/runs/{state['run_id']}").json() == state  # One event, replayed exactly.
    world.rulings.append(blow(guard, "wounded"))  # The /craft path during an encounter is the stranger's part of a round.
    world.intents.append("listen")
    world.replies.append(said("tell_to_leave", impression=0, suspicion=4, anger=3))
    reply = world.http.post(f"/runs/{state['run_id']}/craft", json={
        "text": "shove the guard", "selected_ids": [], "expected_version": state["event_seq"], "request_id": "shove"})
    assert reply.status_code == 200, reply.text
    state = reply.json()["state"]
    assert npc(state, guard)["health"] < 100 and state["last_round"]["replier"] == guard
    world.intents.append("listen")
    state = post(world, state, "encounter/act", {"kind": "leave"})["state"]
    assert state["encounter"] is None and state["last_round"]["ended"]
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
    post(world, state, "explore", {"elapsed_ms": 1000})  # The clock runs again.


def test_speaking_to_someone_is_an_encounter_you_can_simply_walk_away_from(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    person = npc(state, "npc_kade_east")
    cells, (x, y) = [], (state["player"]["x"], state["player"]["y"])
    while max(abs(x - person["x"]), abs(y - person["y"] - 1)) > 0:
        x += (person["x"] > x) - (person["x"] < x)
        y += (person["y"] + 1 > y) - (person["y"] + 1 < y)
        cells.append([x, y])
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i:i + 20]})["state"]
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": "npc_kade_east", "text": "Evening."})["state"]
    assert state["encounter"]["reason"] == "talk" and not encounter.hostile(state)
    post(world, state, "move", {"cells": [[state["player"]["x"], state["player"]["y"] + 1]]})  # Not held.
    assert post(world, state, "encounter/act", {"kind": "wait"}, status=409)["detail"]["reason"] == "stale_state"
