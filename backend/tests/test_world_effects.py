"""Effects that really change the world: raising the gate beam, gifts and barter."""

import copy

from test_craft import commit, fresh_state, judged
from test_talk import npc, said

import briefing
import conversation
import crafting
import patch
import perception
import reputation
import talk


def at_gate(state):
    state["player"].update(x=51, y=11)  # Between the new beam (54, 13) and the brackets across the gate (48, 9).
    return state


def lift_out(aids=()):
    return judged("lift_out", effort_seconds=120, lift_out={"object_id": "gate_bar", "aid_ids": list(aids)})


def install(aids=()):
    return judged(
        "install",
        effort_seconds=120,
        install={"object_id": "gate_beam", "into_id": "gate_brackets", "aid_ids": list(aids)},
    )


def test_the_cracked_bar_comes_out_before_the_new_beam_goes_in():
    state = at_gate(fresh_state())
    for item in ("rope_tomas", "ladder_tomas"):
        state["objects"][item].update(holder_id="player", lent_to="player")  # Tomas lent them.
    full = crafting.validate(state, install(["rope_tomas", "ladder_tomas"]))
    assert full["category"] == "blocked" and "cracked gate bar" in full["reason"]  # One bar at a time.
    heavy = crafting.validate(state, lift_out())
    assert heavy["category"] == "blocked" and "too heavy" in heavy["reason"]
    commit(state, lift_out(["rope_tomas", "ladder_tomas"]), text="lower the cracked bar with rope and ladder")
    bar = state["objects"]["gate_bar"]
    assert bar["installed_in"] is None and bar["condition"] == "usable" and state["gate_open"]
    summary = commit(state, install(["rope_tomas", "ladder_tomas"]), text="raise the beam with rope and ladder")
    beam = state["objects"]["gate_beam"]
    assert summary["category"] == "success" and summary["property"] == []  # His beam, his lent tools: no theft.
    assert beam["installed_in"] == "gate_brackets" and (beam["x"], beam["y"]) == (48, 9)
    assert not state["gate_open"]  # Barred again, with a sound beam.
    assert crafting.validate(state, install(["rope_tomas"]))["category"] in ("blocked", "unresolved")  # Already up.
    seen = perception.perceive(state, state["last_action"])
    roderic = next(p for p in seen if p["npc_id"] == "npc_roderic_vale")
    assert roderic["memory"]["kind"] == "demonstration" and "beam" in roderic["memory"]["summary"]
    assert not roderic["think"]


def test_only_fixtures_take_an_install():
    state = at_gate(fresh_state())
    state["objects"]["rope_tomas"]["holder_id"] = "player"
    wrong = judged("install", install={"object_id": "rope_tomas", "into_id": "trough_gate", "aid_ids": []})
    assert crafting.validate(state, wrong)["category"] in ("blocked", "unresolved")


def test_tomas_counts_the_deal_done_only_once_the_beam_is_up():
    state = at_gate(fresh_state())
    tomas = npc(state, "npc_tomas_reed")
    state["event_seq"] = 1
    talk.exchange(state, "npc_tomas_reed", "Work?", said("offer:beam_help"), "offer:beam_help", "Get it up.", [])
    deal = next(iter(state["agreements"].values()))
    deal["status"] = "accepted"
    assert not conversation.deal_possible(state, deal)
    state["objects"]["gate_beam"]["installed_in"] = "gate_brackets"
    assert (
        conversation.deal_possible(state, deal)
        and "done" in briefing.request(state, npc(state, "npc_tomas_reed"), "Done.")[1]
    )
    assert tomas


def trade(give, want, recipient="npc_darin_ko"):
    return judged(
        "offer_trade", offer_trade={"give_ids": list(give), "want_ids": list(want), "recipient_id": recipient}
    )


def test_an_offered_trade_happens_only_if_they_accept():
    state = fresh_state(79, 32)
    blocked = crafting.validate(state, trade(["flint_a"], ["lodestone_darin"]))
    assert blocked["category"] == "blocked"  # Not in your hands.
    state["objects"]["flint_a"]["holder_id"] = "player"
    commit(state, trade(["flint_a"], ["lodestone_darin"]), text="offer Darin my flint for his stone")
    (offer,) = state["trades"].values()
    assert offer["status"] == "offered" and state["objects"]["lodestone_darin"]["owner_id"] == "npc_darin_ko"
    darin = npc(state, "npc_darin_ko")
    options = conversation.replies(state, darin)
    assert f"accept_trade:{offer['id']}" in options
    assert "offering Darin a trade" in briefing.request(state, darin, "Well?")[0]
    before = copy.deepcopy(state)
    talk.exchange(
        state, "npc_darin_ko", "Deal?", said(f"accept_trade:{offer['id']}"), f"accept_trade:{offer['id']}", "Done.", []
    )
    assert state["objects"]["lodestone_darin"]["holder_id"] == "player"
    assert state["objects"]["lodestone_darin"]["owner_id"] == "player"
    assert (
        state["objects"]["flint_a"]["owner_id"] == "npc_darin_ko"
        and state["trades"][offer["id"]]["status"] == "accepted"
    )
    assert not conversation.open_trades(state, npc(state, "npc_darin_ko"))
    replayed = patch.snapshot(before)  # What the event saves replays to the same world (D-58).
    patch.apply(replayed, patch.diff(patch.snapshot(before), patch.snapshot(state)))
    assert replayed == patch.snapshot(state)


def test_people_give_things_only_to_someone_they_trust():
    state = fresh_state(79, 32)
    darin = npc(state, "npc_darin_ko")
    assert not any(k.startswith("give:") for k in conversation.replies(state, darin))
    reputation.regard(darin)["trust"] = 0.6
    key = next(k for k in conversation.replies(state, darin) if k.startswith("give:"))
    item = key.split(":")[1]
    talk.exchange(state, "npc_darin_ko", "Could you spare it?", said(key), key, "Take it.", [])
    assert state["objects"][item]["holder_id"] == "player" and state["objects"][item]["owner_id"] == "player"
