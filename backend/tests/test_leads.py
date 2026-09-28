"""Readable progress and variety: leads, regard cues, refusals that point somewhere, styles, interjections."""
import encounter
import minds
import talk
from test_encounter import face_to_face, post, world  # noqa: F401  (the fixture is used by name)
from test_talk import npc, said, unit_state


def beside(state, npc_id):
    person = npc(state, npc_id)
    state["player"].update(x=person["x"], y=person["y"] + 1)
    return person


def test_what_people_tell_you_becomes_leads():
    state = unit_state()
    beside(state, "npc_hessa_marr")
    shared = talk.exchange(state, "npc_hessa_marr", "Anyone need help?", said("share:tomas_beam"), "share:tomas_beam",
                           "Tomas has been fighting that beam.", [])
    assert shared["learned"][0]["lead"].startswith("Tomas the carpenter is struggling")
    state["event_seq"] += 1
    referred = talk.exchange(state, "npc_hessa_marr", "Where is he?", said("refer:npc_tomas_reed"),
                             "refer:npc_tomas_reed", "Go and see Tomas.", [])
    assert referred["learned"][0]["lead"] == "Hessa suggested you talk to Tomas, the carpenter."
    state["event_seq"] += 1
    offered = talk.exchange(state, "npc_hessa_marr", "Any work?", said("offer:water_haul"), "offer:water_haul",
                            "Bring me water.", [])
    assert offered["learned"][0]["lead"] == "Hessa asked you to bring them a container full of water from the trough for her kitchen."
    state["event_seq"] += 1
    lent = talk.exchange(state, "npc_hessa_marr", "May I borrow the bucket?", said("lend:bucket_hessa"),
                         "lend:bucket_hessa", "Take it.", [])
    assert lent["learned"][0]["lead"] == "Hessa lent you their wooden bucket."


def test_cues_show_only_when_regard_crosses_a_band():
    state = unit_state()
    darin = npc(state, "npc_darin_ko")
    view = minds.regard(darin)  # trust 0.30, suspicion 0.48
    minds.regard_cue(darin, dict(view), {**view, "trust": 0.33})
    assert "cue" not in darin["mind"]  # Still the same band: nothing to see.
    minds.regard_cue(darin, dict(view), {**view, "trust": 0.5})
    assert darin["mind"]["cue"]["kind"] == "warmer" and darin["mind"]["cue"]["text"].startswith("Darin")
    key = darin["mind"]["cue"]["key"]
    minds.regard_cue(darin, dict(view), {**view, "suspicion": 0.65})
    assert darin["mind"]["cue"]["kind"] == "wary" and darin["mind"]["cue"]["key"] != key
    # Evidence moves regard, and so shows: a clear, working demonstration.
    hessa = npc(state, "npc_hessa_marr")
    minds.remember(hessa, {"kind": "demonstration", "severity": 1, "event": 5, "clarity": "clear", "works": True,
                           "summary": "The stranger's pulley lifted the log.", "short": "x", "victim": None,
                           "source": "shown"})
    assert hessa["mind"]["cue"]["kind"] in ("warmer", "easier")


def test_refusals_carry_what_would_change_their_mind_and_everyone_has_a_voice():
    state = unit_state()
    darin = beside(state, "npc_darin_ko")
    refusing = talk.voice_context(state, darin, "Lend me the stone.", "refuse")
    assert "sell" in refusing["what_would_change_their_mind"] and "friend" in refusing["how_they_talk"]["style"]
    assert "what_would_change_their_mind" not in talk.voice_context(state, darin, "Hello.", "answer")
    assert all(minds.card(n).get("style") and minds.card(n).get("persuaded_by") for n in state["npcs"])
    # Every character sheet is complete: a voice of their own, wants, likes, people they know, things to do.
    for n in state["npcs"]:
        me = minds.card(n)
        assert len(me["voice"]["samples"]) >= 4 and me["voice"]["habits"] and me["goals"] and me["opinions"]             and me["tasks"] and me["secrets"] and me["mood"], n["id"]


def test_asking_back_is_rare():
    state = unit_state()
    tomas = beside(state, "npc_tomas_reed")
    talk.turns(tomas).extend([{"who": "stranger", "text": "Hi"}, {"who": "them", "text": "Who are you?",
                                                                   "reply": "ask_back"}])
    for _ in range(2):
        assert "ask_back" not in talk.replies(state, tomas)
        talk.turns(tomas).extend([{"who": "stranger", "text": "..."}, {"who": "them", "text": "Hm.", "reply": "answer"}])
    talk.turns(tomas).extend([{"who": "stranger", "text": "..."}, {"who": "them", "text": "Hm.", "reply": "answer"}])
    assert "ask_back" in talk.replies(state, tomas)  # Four of their replies later, they may ask again.


def test_someone_else_in_the_encounter_can_cut_in():
    state = unit_state()
    hessa = face_to_face(state, "npc_hessa_marr", reason="talk")
    assert "interject" not in {o["action"] for o in encounter.intent_options(state, hessa).values()}  # Alone.
    bren = npc(state, "npc_bren_marr")
    bren.update(x=hessa["x"] + 1, y=hessa["y"])
    encounter.join(state, bren, "confront", "What's this?", state["sim_time_ms"])
    assert "interject" in {o["action"] for o in encounter.intent_options(state, bren).values()}
    state["encounter"]["intents"]["npc_bren_marr"] = {"action": "interject", "line": None, "line_id": None}
    state["event_seq"] += 1
    _, record = encounter.resolve(state, "run", {"kind": "say", "text": "Hello both.", "target_id": "npc_hessa_marr"},
                                  None, None, "t")
    assert record["replier"] == "npc_hessa_marr" and record["interjector"] == "npc_bren_marr"


def test_an_interjection_is_a_second_reply_in_the_same_round(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    cells = [[48, y] for y in range(67, 15, -1)]
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i:i + 20]})["state"]
    for _ in range(60):
        if state.get("encounter"):
            break
        state = post(world, state, "explore", {"elapsed_ms": 1000})["state"]
    guard = state["encounter"]["participants"][0]
    other = next(n for n in ("npc_oren_dast", "npc_bren_marr", "npc_roderic_vale") if n != guard)
    world.replies.extend([said("answer"), said("ask_back")])
    state = post(world, state, "encounter/act", {"kind": "say", "text": "Hello.", "target_id": other})["state"]
    assert other in state["encounter"]["participants"]
    world.intents.append({guard.split("_")[1]: "interject", other.split("_")[1]: "listen"})
    world.replies.extend([said("answer"), said("ask_back")])
    body = post(world, state, "encounter/act", {"kind": "say", "text": "I'm a traveller.", "target_id": other})
    kinds = [e["kind"] for e in body["round"]["entries"]]
    assert kinds.count("reply") == 1 and kinds.count("interject") == 1
    assert world.http.get(f"/runs/{state['run_id']}").json() == body["state"]
