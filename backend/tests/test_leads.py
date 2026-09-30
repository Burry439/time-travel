"""Readable progress and variety: leads, regard cues, refusals that point somewhere, styles, interjections."""

from test_encounter import face_to_face, post, world  # noqa: F401  (the fixture is used by name)
from test_talk import npc, said, unit_state

import crafting
import minds
import talk


def beside(state, npc_id):
    person = npc(state, npc_id)
    state["player"].update(x=person["x"], y=person["y"] + 1)
    return person


def test_what_people_tell_you_becomes_leads():
    state = unit_state()
    beside(state, "npc_hessa_marr")
    shared = talk.exchange(
        state,
        "npc_hessa_marr",
        "Anyone need help?",
        said("share:tomas_beam"),
        "share:tomas_beam",
        "Tomas has been fighting that beam.",
        [],
    )
    assert shared["learned"][0]["lead"].startswith("Tomas the carpenter is struggling")
    state["event_seq"] += 1
    referred = talk.exchange(
        state,
        "npc_hessa_marr",
        "Where is he?",
        said("refer:npc_tomas_reed"),
        "refer:npc_tomas_reed",
        "Go and see Tomas.",
        [],
    )
    assert referred["learned"][0]["lead"] == "Hessa suggested you talk to Tomas, the carpenter."
    state["event_seq"] += 1
    offered = talk.exchange(
        state, "npc_hessa_marr", "Any work?", said("offer:water_haul"), "offer:water_haul", "Bring me water.", []
    )
    assert offered["learned"][0]["lead"] == (
        "Hessa's request: bring Hessa a container full of water from the trough "
        "for her kitchen. You may use Hessa's wooden bucket and water trough for it."
    )
    state["event_seq"] += 1
    lent = talk.exchange(
        state, "npc_hessa_marr", "May I borrow the cup?", said("lend:cup_hessa"), "lend:cup_hessa", "Take it.", []
    )
    assert lent["learned"][0]["lead"] == "Hessa lent you their wooden cup."


def test_a_job_lends_what_it_needs_so_using_it_is_not_theft():
    """Hessa asks for water and says the bucket's by the trough: taking it to do the job isn't stealing (D-55)."""
    state = unit_state()
    beside(state, "npc_hessa_marr")
    assert [c["id"] for c in crafting._property(state, ["bucket_hessa"], "taken")] == ["bucket_hessa"]
    offered = talk.exchange(
        state,
        "npc_hessa_marr",
        "Any work?",
        said("offer:water_haul"),
        "offer:water_haul",
        "Bring me water; the bucket's by the trough.",
        [],
    )
    assert {t["id"] for t in offered["lent"]} == {"bucket_hessa", "trough_hessa"}
    assert crafting._property(state, ["bucket_hessa", "trough_hessa"], "taken") == []
    assert crafting._property(state, ["honey_hessa"], "taken")  # Only what the job needs.
    # Handed back to her, the loan is over: taking it again would be taking it.
    state["objects"]["bucket_hessa"]["holder_id"] = "player"
    crafting._apply_step(
        state,
        {"given": {"ids": ["bucket_hessa"], "to": "npc_hessa_marr", "owners": {"bucket_hessa": "npc_hessa_marr"}}},
    )
    assert "lent_to" not in state["objects"]["bucket_hessa"]
    assert crafting._property(state, ["bucket_hessa"], "taken")


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
    minds.remember(
        hessa,
        {
            "kind": "demonstration",
            "severity": 1,
            "event": 5,
            "clarity": "clear",
            "works": True,
            "summary": "The stranger's pulley lifted the log.",
            "short": "x",
            "victim": None,
            "source": "shown",
        },
    )
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
        assert (
            len(me["voice"]["samples"]) >= 4
            and me["voice"]["habits"]
            and me["goals"]
            and me["opinions"]
            and me["tasks"]
            and me["secrets"]
            and me["mood"]
        ), n["id"]


def test_asking_back_is_rare():
    state = unit_state()
    tomas = beside(state, "npc_tomas_reed")
    talk.turns(tomas).extend(
        [{"who": "stranger", "text": "Hi"}, {"who": "them", "text": "Who are you?", "reply": "ask_back"}]
    )
    for _ in range(2):
        assert "ask_back" not in talk.replies(state, tomas)
        talk.turns(tomas).extend(
            [{"who": "stranger", "text": "..."}, {"who": "them", "text": "Hm.", "reply": "answer"}]
        )
    talk.turns(tomas).extend([{"who": "stranger", "text": "..."}, {"who": "them", "text": "Hm.", "reply": "answer"}])
    assert "ask_back" in talk.replies(state, tomas)  # Four of their replies later, they may ask again.
