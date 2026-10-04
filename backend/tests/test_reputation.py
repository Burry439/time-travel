"""Reputation (GDD D-43): respect for competence seen working, awe at the uncanny (double-edged, by each
person's superstition), and any guard letting the stranger in for their own reasons."""

from test_gate import answers
from test_talk import npc, unit_state

import briefing
import cast
import conversation
import gatekeeping
import minds
import perception
import reputation
import talk
import tuning


def shown(wonder, works=True):
    return {
        "event_id": 7,
        "category": "success",
        "action": "demonstrate",
        "property": [],
        "demonstration": {
            "object_id": "needle_x",
            "object_name": "floating needle",
            "used_ids": [],
            "audience_ids": [],
            "observed": "The stranger's needle swung round and settled north.",
            "works": works,
            "results": [],
            "wonder": wonder,
        },
    }


def watching(*people):
    state = unit_state()
    state["player"].update(x=40, y=40)
    for n, npc_id in enumerate(people):
        npc(state, npc_id).update(x=41 + n, y=40)
    return state


def test_most_people_are_awed_by_a_wonder_the_superstitious_are_afraid_instead():
    """D-63 (the user: "most people should be able to be awed, but some should be superstitious, depending on the
    character"). Seen with their own eyes: Tomas (none) is awed, Jory (reverent) doubly, Roderic (wary) is afraid and
    not awed. Trust is still each person's own to give."""
    state = watching("npc_jory_venn", "npc_roderic_vale", "npc_tomas_reed")
    jory, roderic, tomas = (npc(state, i) for i in ("npc_jory_venn", "npc_roderic_vale", "npc_tomas_reed"))
    trust = {n["id"]: reputation.regard(n)["trust"] for n in (jory, roderic, tomas)}
    perception.apply_perceptions(state, perception.perceive(state, shown("uncanny")))
    assert reputation.regard(tomas)["awe"] == tuning.AWE_SHIFT
    assert reputation.regard(jory)["awe"] == 2 * tuning.AWE_SHIFT
    assert reputation.regard(roderic)["awe"] == 0 and roderic["mind"]["feelings"]["fear"] == tuning.SUPERSTITIOUS_FEAR
    assert len(reputation.feared_wonders(roderic)) == 1 and not reputation.feared_wonders(tomas)
    assert {n["id"]: reputation.regard(n)["trust"] for n in (jory, roderic, tomas)} == trust
    perception.apply_perceptions(state, perception.perceive(state, {**shown("uncanny"), "event_id": 9}))
    assert reputation.regard(tomas)["awe"] == tuning.AWE_SHIFT  # The same wonder again: no more awe.
    clever = watching("npc_tomas_reed")
    perception.apply_perceptions(clever, perception.perceive(clever, shown("clever")))
    assert reputation.regard(npc(clever, "npc_tomas_reed"))["awe"] == 0  # Clever is not uncanny.


def test_explained_properly_a_superstitious_person_is_awed_too():
    """D-63: even a superstitious person can be awed if the stranger explains the thing properly. Whether it made
    sense is the person's own reading in their own call; bluster explains nothing."""
    state = watching("npc_roderic_vale")
    roderic = npc(state, "npc_roderic_vale")
    perception.apply_perceptions(state, perception.perceive(state, shown("uncanny")))
    person = briefing.scene_context(state, roderic, [roderic], [], "Let me explain.", None)["people"][0]
    assert "wonder" in person["_rules"] and "witchcraft" in person["a_wonder_that_frightens_you"][0]
    talk.exchange(state, "npc_roderic_vale", "It's a gift from the gods.", {}, "answer", "Witchcraft.", [])
    assert reputation.feared_wonders(roderic) and reputation.regard(roderic)["awe"] == 0  # Bluster: still afraid.
    understood = {"understood": {"type": "noul", "noul": 0.9}}
    words = "The needle was rubbed on a lodestone; it turns to the north as the stone does. Watch, I'll do it again."
    talk.exchange(state, "npc_roderic_vale", words, understood, "answer", "Hm. So that's all it is.", [])
    assert not reputation.feared_wonders(roderic) and reputation.regard(roderic)["awe"] == tuning.AWE_SHIFT
    assert roderic["mind"]["feelings"]["fear"] == 0
    after = briefing.scene_context(state, roderic, [roderic], [], "Hello.", None)["people"][0]
    assert "wonder" not in after["_rules"] and "a_wonder_that_frightens_you" not in after


def test_a_working_thing_is_evidence_awaiting_personal_judgment():
    state = watching("npc_kade_east", "npc_tomas_reed")
    kade = npc(state, "npc_kade_east")
    before = dict(reputation.regard(kade))
    perception.apply_perceptions(state, perception.perceive(state, shown("clever")))
    assert reputation.regard(kade) == before
    talk.update_regard(kade, {"respect": {"score": 4}, "impression": {"score": 3}, "suspicion": {"score": 2}})
    assert reputation.regard(kade)["respect"] > before["respect"]
    assert reputation.regard(npc(state, "npc_tomas_reed"))["respect"] == 0


def test_a_wonder_can_be_read_differently_by_each_person():
    state = watching("npc_jory_venn", "npc_roderic_vale")
    perception.apply_perceptions(state, perception.perceive(state, shown("uncanny")))
    jory, roderic = (npc(state, i) for i in ("npc_jory_venn", "npc_roderic_vale"))
    talk.update_regard(jory, {"impression": {"score": 4}, "suspicion": {"score": 1}, "awe": {"score": 4}})
    talk.update_regard(roderic, {"impression": {"score": 1}, "suspicion": {"score": 4}, "fear": {"score": 0.67}})
    assert reputation.regard(jory)["awe"] > 0
    assert reputation.regard(roderic)["awe"] == 0
    assert roderic["mind"]["feelings"]["fear"] == 0.67


def test_a_wonder_repeated_does_not_renew_evidence():
    state = watching("npc_jory_venn", "npc_roderic_vale")
    perception.apply_perceptions(state, perception.perceive(state, shown("uncanny")))
    for n in (npc(state, i) for i in ("npc_jory_venn", "npc_roderic_vale")):
        assert len(n["mind"]["evidence"]) == 1
    again = shown("uncanny")
    again["event_id"] = 8
    perception.apply_perceptions(state, perception.perceive(state, again))
    for n in (npc(state, i) for i in ("npc_jory_venn", "npc_roderic_vale")):
        assert len(n["mind"]["evidence"]) == 1


def test_stories_of_wonders_earn_no_awe():
    state = unit_state()
    oren = npc(state, "npc_oren_dast")
    reputation.remember(
        oren,
        {
            "kind": "demonstration",
            "severity": 1,
            "event": 9,
            "clarity": "told",
            "victim": None,
            "source": "told_by:npc_jory_venn",
            "works": True,
            "wonder": "uncanny",
            "summary": "Jory told them the stranger's needle finds north by itself.",
            "short": "showed off a needle",
        },
    )
    assert reputation.regard(oren)["awe"] == 0  # Claims and stories never do (GDD 1).


def test_the_sheets_carry_superstition_and_regard_in_words():
    state = watching("npc_jory_venn")
    perception.apply_perceptions(state, perception.perceive(state, shown("uncanny")))
    reputation.regard(npc(state, "npc_jory_venn"))["awe"] = 0.25  # The person chose this reading.
    text = minds.situation(state, npc(state, "npc_jory_venn"))
    assert "Wonders and the uncanny:" in text and "awe a touch" in text


def test_bren_lets_you_in_on_his_own_rule():
    state = unit_state()
    bren = npc(state, "npc_bren_marr")
    state["player"].update(x=bren["x"], y=bren["y"] + 1)
    assert gatekeeping.grounds_to_admit(bren)  # A rule of his own (D-62): whether a stranger meets it is his call.
    reputation.regard(bren).update(trust=0.7, suspicion=0.2)  # He has come to trust them himself.
    cast.mind(bren)["met"] = True
    assert gatekeeping.grounds_to_admit(bren)
    _, questions = briefing.request(state, bren, "Will you let me through?")
    key = conversation.decided_reply(state, bren, answers("admit", reason=0.8, threat=0.1), "admit")
    assert key == "admit"
    state["event_seq"] = 3
    said = talk.exchange(
        state,
        bren["id"],
        "Will you let me through?",
        answers("ask_back", reason=0.8, threat=0.1),
        key,
        "Go on, then. Quick, before the captain sees.",
        [],
    )
    assert said["admission"]["by"] == "npc_bren_marr" and state["gate_open"]
