"""Reputation (GDD D-43): respect for competence seen working, awe at the uncanny (double-edged, by each
person's superstition), and any guard letting the stranger in for their own reasons."""

from test_gate import answers
from test_talk import npc, unit_state

import cast
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


def test_a_clever_thing_earns_respect_and_an_ordinary_one_less():
    state = watching("npc_kade_east", "npc_tomas_reed")
    perception.apply_perceptions(state, perception.perceive(state, shown("clever")))
    kade = reputation.regard(npc(state, "npc_kade_east"))
    assert abs(kade["respect"] - 2 * tuning.EVIDENCE_SHIFT) < 1e-9 and kade["awe"] == 0
    other = watching("npc_kade_east")
    perception.apply_perceptions(other, perception.perceive(other, shown("ordinary")))
    assert reputation.regard(npc(other, "npc_kade_east"))["respect"] == tuning.EVIDENCE_SHIFT


def test_awe_is_double_edged():
    state = watching("npc_jory_venn", "npc_roderic_vale", "npc_tomas_reed")
    before = {
        i: dict(reputation.regard(npc(state, i))) for i in ("npc_jory_venn", "npc_roderic_vale", "npc_tomas_reed")
    }
    perception.apply_perceptions(state, perception.perceive(state, shown("uncanny")))
    jory, roderic, tomas = (reputation.regard(npc(state, i)) for i in before)
    assert jory["awe"] > 0 and roderic["awe"] > 0 and tomas["awe"] > 0
    # Jory is reverent: touched by the gods. Trust rises beyond any ordinary proof.
    assert jory["trust"] - before["npc_jory_venn"]["trust"] > 2 * tuning.EVIDENCE_SHIFT - 1e-9
    # Roderic is wary: witchcraft. No credit, more suspicion, and he's uneasy.
    assert roderic["trust"] == before["npc_roderic_vale"]["trust"]
    assert roderic["suspicion"] > before["npc_roderic_vale"]["suspicion"]
    assert npc(state, "npc_roderic_vale")["mind"]["feelings"]["fear"] > 0.3
    # Tomas is neither: an ordinary piece of evidence.
    assert abs(tomas["trust"] - before["npc_tomas_reed"]["trust"] - tuning.EVIDENCE_SHIFT) < 1e-9


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
    text = minds.situation(state, npc(state, "npc_jory_venn"))
    assert "Wonders and the uncanny:" in text and "awe a touch" in text


def test_bren_lets_you_in_on_his_own_rule():
    state = unit_state()
    bren = npc(state, "npc_bren_marr")
    state["player"].update(x=bren["x"], y=bren["y"] + 1)
    assert not talk.grounds_to_admit(bren)  # A stranger he doesn't know: nothing to go on (D-55).
    reputation.regard(bren).update(trust=0.7, suspicion=0.2)  # He has come to trust them himself.
    cast.mind(bren)["met"] = True
    assert talk.grounds_to_admit(bren)
    _, questions = talk.request(state, bren, "Will you let me through?")
    key = talk.decided_reply(state, bren, answers("admit", reason=0.8, threat=0.1), "admit")
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
