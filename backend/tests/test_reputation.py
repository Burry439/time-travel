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
    assert gatekeeping.grounds_to_admit(bren)  # A stranger he doesn't know: nothing to go on (D-55).
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
