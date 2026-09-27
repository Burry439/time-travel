"""NPC minds with a scripted decider: perception, the report chain, attacks on the player, rewind."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as service
import encounter
import minds
from ai import decider


def unit_state():
    state = service.initial_state({"id": "mind0000", "mode": "developer", "seed_version": service.SEED_VERSION,
                                   "geometry_version": service.GEOMETRY_VERSION})
    state.setdefault("pending_minds", [])
    return state


def npc(state, npc_id):
    return minds.find(state["npcs"], npc_id)


def place(state, npc_id, x, y):
    person = npc(state, npc_id)
    person["x"], person["y"] = x, y
    return person


def killing(victim):
    return {"event_id": 1, "category": "success", "action": "harm", "property": [],
            "harm": {"target_id": victim, "weapon_id": None, "method": "melee", "result": "killed",
                     "injury": "a blow", "witnesses": []}}


def answers(action, fear=2, anger=2, believes=0.9, result=None):
    """Jev-shaped answers."""
    out = {"action": {"type": "choice", "choice": action, "confidence": 0.9, "probabilities": {action: 0.9}},
           "fear": {"type": "score", "score": fear}, "anger": {"type": "score", "score": anger},
           "believes": {"type": "noul", "noul": believes}}
    if result:
        out["result"] = {"type": "choice", "choice": result, "probabilities": {result: 1.0}}
    return out


def test_only_people_who_can_see_it_remember_it():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_tomas_reed", 41, 40)
    place(state, "npc_jory_venn", 45, 41)  # In the open, 5 cells away.
    place(state, "npc_mara_venn", 30, 46)  # Behind the inn (cells 25-43 x 44-49).
    seen = minds.perceive(state, killing("npc_tomas_reed"))
    minds.apply_perceptions(state, seen)
    witnesses = {p["npc_id"] for p in seen}
    assert "npc_jory_venn" in witnesses and "npc_mara_venn" not in witnesses
    memory = npc(state, "npc_jory_venn")["mind"]["memories"][-1]
    assert memory["source"] == "witnessed" and "Tomas" in memory["summary"] and memory["severity"] == 3
    assert {"npc_id": "npc_jory_venn", "kind": "decide", "why": "witnessed"} in state["pending_minds"]


def test_legal_actions_come_from_code():
    state = unit_state()
    options = minds.legal_actions(state, npc(state, "npc_jory_venn"))
    bases = {key.split("|")[0].split(":")[0] for key in options}
    assert {"carry_on", "watch", "flee", "hide", "shout_for_help", "confront", "attack", "report"} <= bases
    assert "whistle" not in bases  # Guards only.
    assert not any(key.startswith("report:npc_jory") for key in options)
    assert any(key.startswith("report:npc_mara_venn") for key in options)  # Family, not only guards.
    assert all("Says:" in text for key, text in options.items() if key.startswith("flee"))


def run_until(state, done, limit_ms=60_000, beat=500):
    for _ in range(limit_ms // beat):
        state["npcs"], heard, state["player"] = minds.advance_world(state, beat, state["sim_time_ms"])
        state["sim_time_ms"] += beat
        if done():
            return True
    return False


def test_witness_reports_to_a_guard_who_attacks_and_can_kill():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_tomas_reed", 41, 40)
    place(state, "npc_jory_venn", 45, 41)
    bren = place(state, "npc_bren_marr", 52, 36)
    minds.apply_perceptions(state, minds.perceive(state, killing("npc_tomas_reed")))
    jory = npc(state, "npc_jory_venn")
    journal = []
    record = minds.apply_decision(state, jory, answers("report:npc_bren_marr"), state["sim_time_ms"], journal)
    assert record["action"].startswith("report:npc_bren_marr|") and jory["mind"]["job"]["kind"] == "report"
    assert state["pending_minds"] and state["pending_minds"][0]["npc_id"] == "npc_jory_venn"
    state["pending_minds"] = []
    assert run_until(state, lambda: any(p["npc_id"] == "npc_bren_marr" for p in state["pending_minds"]))
    bren = npc(state, "npc_bren_marr")
    told = bren["mind"]["memories"][-1]
    assert told["source"] == "told_by:npc_jory_venn" and "Tomas" in told["summary"]
    assert "Bren" in npc(state, "npc_jory_venn")["mind"]["said"]["text"]
    request_text, questions = minds.decision_request(state, state["pending_minds"][0])
    assert "believes" in questions and "Jory told them" in request_text
    state["pending_minds"] = []
    minds.apply_decision(state, bren, answers("attack"), state["sim_time_ms"], journal)
    # Reaching the stranger opens an encounter: no blows on the clock, only in its rounds.
    assert run_until(state, lambda: bool(state.get("encounter")), limit_ms=60_000)
    assert state["player"].get("health", 100) == 100
    assert state["encounter"]["participants"] == ["npc_bren_marr"]
    assert state["encounter"]["intents"]["npc_bren_marr"]["action"] == "attack"
    for _ in range(30):  # The stranger just waits; Bren keeps attacking. Blows are a seeded roll on weapon and skill.
        if not state["player"]["alive"]:
            break
        state["event_seq"] += 1
        state, record = encounter.resolve(state, "mind0000", {"kind": "wait", "text": "", "target_id": None},
                                          None, None, "t")
        encounter.finish(state, record, state["sim_time_ms"])
        if state.get("encounter"):
            state["encounter"]["intents"]["npc_bren_marr"] = {"action": "attack", "line": None, "line_id": None}
    assert not state["player"]["alive"] and not state.get("encounter")
    bren = npc(state, "npc_bren_marr")
    assert minds.math.dist((bren["x"], bren["y"]), minds.player_cell(state)) <= 1.5
    assert bren["mind"]["job"]["kind"] == "watch"  # Attackers stand down once the stranger is dead.


def test_routine_people_ignore_jobs_they_do_not_have():
    state = unit_state()
    start = [(n["x"], n["y"]) for n in state["npcs"]]
    assert run_until(state, lambda: [(n["x"], n["y"]) for n in state["npcs"]] != start, limit_ms=10_000)


@pytest.fixture
def scripted(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "minds.sqlite3")
    monkeypatch.setattr(service, "ASSET_DIR", tmp_path / "assets")
    script = []

    def fake_decide(situation, questions):
        prefixes = sorted({key.split("__")[0] + "__" for key in questions if "__" in key}) or [""]
        replies = {}
        for prefix in prefixes:
            reply = script.pop(0)
            replies.update({prefix + key: value for key, value in reply.items()})
        return decider.DeciderCall(provider="script", model="script", answers=replies)
    monkeypatch.setattr(service.decider, "decide", fake_decide)
    monkeypatch.setattr(service.decider, "decide_many", lambda requests: [fake_decide(*r) for r in requests])
    judge_replies = []
    monkeypatch.setattr(service.judge, "judge_craft", lambda context: service.judge.JudgeCall(
        status="ok", result=judge_replies.pop(0), model="stub", attempts=1))
    return SimpleNamespace(http=TestClient(service.app), script=script, judge=judge_replies)


def walk_to(http, state, x, y):
    while (state["player"]["x"], state["player"]["y"]) != (x, y):
        px, py = state["player"]["x"], state["player"]["y"]
        step = {"x": px + (x > px) - (x < px), "y": py + (y > py) - (y < py),
                "expected_version": state["event_seq"], "request_id": f"walk-{state['event_seq']}"}
        response = http.post(f"/runs/{state['run_id']}/move", json=step)
        assert response.status_code == 200, response.text
        state = response.json()["state"]
    return state


def think(http, state):
    reply = http.post(f"/runs/{state['run_id']}/think", json={
        "expected_version": state["event_seq"], "request_id": f"think-{state['event_seq']}"})
    assert reply.status_code == 200, reply.text
    return reply.json()


def tick(http, state, ms=500):
    reply = http.post(f"/runs/{state['run_id']}/explore", json={
        "elapsed_ms": ms, "expected_version": state["event_seq"], "request_id": f"beat-{state['event_seq']}"})
    assert reply.status_code == 200, reply.text
    return reply.json()["state"]


def test_victim_fights_back_kills_the_player_and_rewind_restores_the_calm(scripted):
    http = scripted.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 36, 52)  # Beside Hessa (34, 51).
    calm_seq = state["event_seq"]
    scripted.judge.append({"clarifying_question": None, "precedent_key": "punch", "steps": [{
        "action": "harm", "outcome": "success", "reason": "You punch Hessa.", "effort_seconds": 1,
        "new_object": None, "take_ids": [], "transformation": None,
        "harm": {"target_id": "npc_hessa_marr", "weapon_id": None, "method": "melee", "result": "wounded",
                 "injury": "a bruised cheek"}}]})
    state = http.post(f"/runs/{state['run_id']}/craft", json={
        "text": "punch Hessa", "selected_ids": [], "expected_version": state["event_seq"],
        "request_id": "punch"}).json()["state"]
    assert state["safe_seq"] == calm_seq
    assert any(p["npc_id"] == "npc_hessa_marr" for p in state["pending_minds"])
    scripted.script.extend(answers("attack") for _ in state["pending_minds"])
    body = think(http, state)
    state = body["state"]
    hessa = minds.find(state["npcs"], "npc_hessa_marr")
    assert hessa["mind"]["job"]["kind"] == "attack" and hessa["mind"]["said"]["text"]
    assert any(e.get("npc_id") == "npc_hessa_marr" for e in state["journal"])  # The player heard her.
    for _ in range(200):  # Hessa punches (fists: no instant kills), so this takes a while.
        if not state["player"]["alive"]:
            break
        if state.get("encounter"):  # Face to face: the stranger just waits, round after round.
            scripted.script.extend(answers("attack") for _ in encounter.missing_intents(state))
            reply = http.post(f"/runs/{state['run_id']}/encounter/act", json={
                "kind": "wait", "expected_version": state["event_seq"], "request_id": f"round-{state['event_seq']}"})
            assert reply.status_code == 200, reply.text
            state = reply.json()["state"]
            continue
        scripted.script.extend(answers("watch") for _ in state["pending_minds"])
        state = think(http, state)["state"] if state["pending_minds"] else tick(http, state, 1000)
    assert any(e.get("kind") == "npc_attack" and e["npc_id"] == "npc_hessa_marr" for e in state["journal"])
    assert state["player"]["alive"] is False and state["player"]["health"] == 0
    assert http.get(f"/runs/{state['run_id']}").json() == state  # Replays exactly.
    traces = http.get(f"/runs/{state['run_id']}/traces").json()
    assert traces["minds"] and "situation" in traces["minds"][0]
    assert http.post(f"/runs/{state['run_id']}/explore", json={
        "elapsed_ms": 500, "expected_version": state["event_seq"], "request_id": "dead"}).status_code == 409
    restored = http.post(f"/runs/{state['run_id']}/rewind").json()
    assert restored["run_id"] != state["run_id"] and restored["event_seq"] == calm_seq
    assert restored["player"].get("alive", True) and minds.find(restored["npcs"], "npc_hessa_marr").get("health") == 100
    assert http.get(f"/runs/{state['run_id']}").json() == state  # The original journey is untouched.


def test_shaken_people_reconsider_a_limited_number_of_times():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_tomas_reed", 41, 40)
    jory = place(state, "npc_jory_venn", 45, 41)
    wounding = killing("npc_tomas_reed")
    wounding["harm"]["result"] = "wounded"
    minds.apply_perceptions(state, minds.perceive(state, wounding))
    state["pending_minds"] = []
    rethinks = 0
    for _ in range(5):
        minds.apply_decision(state, npc(state, "npc_jory_venn"), answers("watch"), state["sim_time_ms"], [])
        run_until(state, lambda: bool(state["pending_minds"]), limit_ms=25_000)
        if state["pending_minds"]:
            rethinks += 1
            state["pending_minds"] = []
    assert rethinks == minds.MAX_RETHINKS


def test_shouts_about_known_events_do_not_echo_forever():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_tomas_reed", 41, 40)
    place(state, "npc_jory_venn", 45, 41)
    place(state, "npc_hessa_marr", 44, 38)  # Both saw the same attack.
    wounding = killing("npc_tomas_reed")
    wounding["harm"]["result"] = "wounded"
    minds.apply_perceptions(state, minds.perceive(state, wounding))
    state["pending_minds"] = []
    minds.apply_decision(state, npc(state, "npc_jory_venn"), answers("shout_for_help"), 0, [])
    assert not any(p["npc_id"] == "npc_hessa_marr" for p in state["pending_minds"])  # Old news to Hessa.
    assert "shout_for_help" not in minds.legal_actions(state, npc(state, "npc_jory_venn"))  # Once per event.
    minds.apply_decision(state, npc(state, "npc_hessa_marr"), answers("shout_for_help"), 0, [])
    assert not any(p["npc_id"] == "npc_jory_venn" for p in state["pending_minds"])


def test_close_witnesses_see_clearly_and_distant_ones_see_a_scuffle():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_tomas_reed", 41, 40)
    place(state, "npc_jory_venn", 44, 40)   # 3-4 cells: sees it all.
    place(state, "npc_darin_ko", 49, 40)    # 8-9 cells: only a scuffle.
    wounding = killing("npc_tomas_reed")
    wounding["harm"]["result"] = "wounded"
    memories = {p["npc_id"]: p["memory"] for p in minds.perceive(state, wounding)}
    assert memories["npc_jory_venn"]["clarity"] == "clear" and "attacked Tomas" in memories["npc_jory_venn"]["summary"]
    assert memories["npc_darin_ko"]["clarity"] == "vague" and "scuffle" in memories["npc_darin_ko"]["summary"]
    assert memories["npc_darin_ko"]["severity"] < memories["npc_jory_venn"]["severity"]


def test_everyone_deciding_shares_one_request():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_tomas_reed", 41, 40)
    place(state, "npc_jory_venn", 44, 40)
    place(state, "npc_darin_ko", 43, 42)
    wounding = killing("npc_tomas_reed")
    wounding["harm"]["result"] = "wounded"
    minds.apply_perceptions(state, minds.perceive(state, wounding))
    text, questions, prefixes = minds.batch_request(state, state["pending_minds"])
    assert set(prefixes) == {"npc_tomas_reed", "npc_jory_venn", "npc_darin_ko"}
    assert all(f"{prefix}action" in questions for prefix in prefixes.values())
    assert "=== JORY" in text and "=== DARIN" in text
    reply = {f"{prefixes['npc_jory_venn']}action": {"choice": "watch"}, f"{prefixes['npc_darin_ko']}fear": {"score": 1}}
    assert minds.answers_for(reply, prefixes["npc_jory_venn"]) == {"action": {"choice": "watch"}}


def test_voices_fit_the_person_and_never_repeat():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_jory_venn", 41, 40)
    mara = place(state, "npc_mara_venn", 43, 41)
    wounding = killing("npc_jory_venn")
    wounding["harm"]["result"] = "wounded"
    minds.apply_perceptions(state, minds.perceive(state, wounding))
    npc(state, "npc_jory_venn")["health"] = 55
    shouts = {k: v for k, v in minds.legal_actions(state, mara).items() if k.startswith("shout_for_help|")}
    assert shouts and any("my nephew" in text for text in shouts.values())  # Protective of her nephew.
    chosen = next(iter(shouts))
    minds.apply_decision(state, mara, {"action": {"choice": chosen}}, 0, [])
    mara["mind"]["shouted"] = []  # Allow shouting again, to check the line itself is not repeated.
    again = {k for k in minds.legal_actions(state, mara) if k.startswith("shout_for_help|")}
    assert chosen not in again
    assert not any(k.startswith("whistle") for k in minds.legal_actions(state, mara))


def test_blows_are_a_repeatable_roll_on_weapon_and_skill():
    first, second = unit_state(), unit_state()
    results = []
    for state in (first, second):
        kade = npc(state, "npc_kade_east")
        results.append([minds.strike(state, kade, t * 2500, [])["result"] for t in range(6)])
    assert results[0] == results[1]
    assert first["player"]["health"] == second["player"]["health"] < 100


def test_victims_speak_in_the_first_person():
    state = unit_state()
    state["player"].update(x=40, y=40)
    place(state, "npc_jory_venn", 41, 40)
    wounding = killing("npc_jory_venn")
    wounding["harm"]["result"] = "wounded"
    memory = next(p["memory"] for p in minds.perceive(state, wounding) if p["npc_id"] == "npc_jory_venn")
    assert memory["short"] == "attacked me"
