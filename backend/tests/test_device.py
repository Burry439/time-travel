"""The device as a companion and coach (D-55): a long memory, what a coach needs (and nothing more), remarks at key
moments (not too often), and the one standing rule everyone uses."""
import app as service
import minds
import tutorial
from ai import voice
from test_encounter import post, world  # noqa: F401


def village_state():
    state = service.initial_state({"id": "dev00000", "mode": "developer", "seed_version": service.SEED_VERSION,
                                   "geometry_version": service.GEOMETRY_VERSION})
    state.setdefault("pending_minds", [])
    return state


def test_it_remembers_the_conversation_and_keeps_a_long_history():
    state = village_state()
    for i in range(30):
        tutorial.device_says(state, f"answer {i}", "answer", f"question {i}")
    assert len(state["device_log"]) == 30
    context = tutorial.device_context(state, "and now?")
    assert len(context["our_conversation"]) == tutorial.CONVERSATION_KEPT
    assert context["our_conversation"][-1] == {"you_asked": "question 29", "i_said": "answer 29"}
    assert context["earlier_questions"][-1] == "question 13"
    for i in range(500):
        tutorial.device_says(state, "x", "answer", "y")
    assert len(state["device_log"]) == tutorial.DEVICE_LOG_KEPT


def test_the_coach_knows_what_the_stranger_knows_and_no_more():
    state = village_state()
    hessa = minds.find(state["npcs"], "npc_hessa_marr")
    minds.mind(hessa)["met"] = True
    state.setdefault("learned", []).append({"npc_id": "npc_hessa_marr", "name": "Hessa", "said": "…",
                                             "lead": "Hessa needs water hauled from the trough."})
    context = tutorial.device_context(state, "what now?")
    assert context["leads_newest_first"][0] == {"lead": "Hessa needs water hauled from the trough.", "from": "Hessa"}
    assert {"name": "Hessa", "role": minds.card(hessa)["role"], "stands": "Neutral"} in context["people_met"]
    flat = str(context)
    assert "secret" not in flat and "late shifts" not in flat and "eleven silver" not in flat  # Nobody's secrets.
    assert not any(p["name"] == "Oren" for p in context["people_met"])  # Only people the stranger has met.


def test_standing_is_one_word_from_regard_anger_and_crimes():
    state = village_state()
    jory = minds.find(state["npcs"], "npc_jory_venn")
    assert minds.standing(jory) == "unknown"
    minds.mind(jory)["met"] = True
    minds.regard(jory).update(trust=0.3, suspicion=0.2)
    assert minds.standing(jory) == "neutral"
    minds.regard(jory)["trust"] = 0.5
    assert minds.standing(jory) == "friendly"
    minds.regard(jory)["trust"] = 0.65
    assert minds.standing(jory) == "would_speak"
    minds.regard(jory)["suspicion"] = 0.7
    assert minds.standing(jory) == "wary"
    minds.mind(jory)["feelings"]["anger"] = 0.7
    assert minds.standing(jory) == "hostile"
    assert minds.update_standing(jory) and minds.mind(jory)["standing"] == "hostile" and not minds.update_standing(jory)


def test_a_moment_is_worth_a_word_only_sometimes(world, monkeypatch):
    """Remarks: only with something to say, at most every two minutes, never face to face, never a written
    stand-in (stub mode has no model, so nothing is said)."""
    state = village_state()
    assert tutorial.moment_detail(state, "new_lead") is None and tutorial.moment_allowed(state)
    tutorial.device_says(state, "Hm.", "remark")
    assert not tutorial.moment_allowed(state)
    state["sim_time_ms"] += tutorial.MOMENT_GAP_MS
    assert tutorial.moment_allowed(state)
    run = world.http.post("/runs", json={"mode": "developer"}).json()
    body = post(world, run, "device/ask", {"moment": "stuck"})
    assert body["skipped"] and not body["state"].get("device_log")  # Stub: no model, no remark.
    monkeypatch.setattr(voice, "device", lambda context, fallback, allowed=True: voice.VoiceCall(
        status="ok", text="Try the inn: Hessa talks to everyone.", prompt_version="device_v2"))
    body = post(world, run, "device/ask", {"moment": "stuck"})
    assert not body.get("skipped") and body["state"]["device_log"][-1]["kind"] == "remark"
    again = post(world, body["state"], "device/ask", {"moment": "stuck"})
    assert again["skipped"]  # Not twice in two minutes.
    assert world.http.post(f"/runs/{run['run_id']}/device/ask", json={
        "expected_version": 0, "request_id": "empty"}).status_code == 422
