"""Effects that really change the world: raising the gate beam, gifts and barter."""
import copy

import crafting
import minds
import talk
from test_craft import commit, fresh_state, judged
from test_talk import npc, said


def at_gate(state):
    state["player"].update(x=54, y=11)  # Between the beam (54, 13) and the brackets (54, 9).
    return state


def install(aids=()):
    return judged("install", effort_seconds=120, install={
        "object_id": "gate_beam", "into_id": "gate_brackets", "aid_ids": list(aids)})


def test_the_beam_needs_real_help_and_then_it_is_up():
    state = at_gate(fresh_state())
    blocked = crafting.validate(state, install())
    assert blocked["category"] == "blocked" and "too heavy" in blocked["reason"]
    for item in ("rope_tomas", "ladder_tomas"):
        state["objects"][item].update(holder_id="player", lent_to="player")  # Tomas lent them.
    summary = commit(state, install(["rope_tomas", "ladder_tomas"]), text="raise the beam with rope and ladder")
    beam = state["objects"]["gate_beam"]
    assert summary["category"] == "success" and summary["property"] == []  # His beam, his lent tools: no theft.
    assert beam["installed_in"] == "gate_brackets" and (beam["x"], beam["y"]) == (54, 9)
    assert crafting.validate(state, install(["rope_tomas"]))["category"] in ("blocked", "unresolved")  # Already up.
    seen = minds.perceive(state, state["last_action"])
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
    assert not talk.deal_possible(state, deal)
    state["objects"]["gate_beam"]["installed_in"] = "gate_brackets"
    assert talk.deal_possible(state, deal) and "done" in talk.request(state, npc(state, "npc_tomas_reed"), "Done.")[1]
    assert tomas


def trade(give, want, recipient="npc_darin_ko"):
    return judged("offer_trade", offer_trade={"give_ids": list(give), "want_ids": list(want),
                                              "recipient_id": recipient})


def test_an_offered_trade_happens_only_if_they_accept():
    state = fresh_state(79, 32)
    blocked = crafting.validate(state, trade(["flint_a"], ["lodestone_darin"]))
    assert blocked["category"] == "blocked"  # Not in your hands.
    state["objects"]["flint_a"]["holder_id"] = "player"
    commit(state, trade(["flint_a"], ["lodestone_darin"]), text="offer Darin my flint for his stone")
    (offer,) = state["trades"].values()
    assert offer["status"] == "offered" and state["objects"]["lodestone_darin"]["owner_id"] == "npc_darin_ko"
    darin = npc(state, "npc_darin_ko")
    options = talk.replies(state, darin)
    assert f"accept_trade:{offer['id']}" in options
    assert "offering Darin a trade" in talk.request(state, darin, "Well?")[0]
    before = copy.deepcopy(state)
    payload = talk.exchange(state, "npc_darin_ko", "Deal?", said(f"accept_trade:{offer['id']}"),
                            f"accept_trade:{offer['id']}", "Done.", [])
    assert state["objects"]["lodestone_darin"]["holder_id"] == "player"
    assert state["objects"]["lodestone_darin"]["owner_id"] == "player"
    assert state["objects"]["flint_a"]["owner_id"] == "npc_darin_ko" and state["trades"][offer["id"]]["status"] == "accepted"
    assert not talk.open_trades(state, npc(state, "npc_darin_ko"))
    replayed = copy.deepcopy(before)  # The event replays to the same world.
    talk.apply_payload(replayed, {**payload, "npcs": state["npcs"]})
    assert replayed["objects"] == state["objects"] and replayed["trades"] == state["trades"]


def test_people_give_things_only_to_someone_they_trust():
    state = fresh_state(79, 32)
    darin = npc(state, "npc_darin_ko")
    assert not any(k.startswith("give:") for k in talk.replies(state, darin))
    minds.regard(darin)["trust"] = 0.6
    key = next(k for k in talk.replies(state, darin) if k.startswith("give:"))
    item = key.split(":")[1]
    talk.exchange(state, "npc_darin_ko", "Could you spare it?", said(key), key, "Take it.", [])
    assert state["objects"][item]["holder_id"] == "player" and state["objects"][item]["owner_id"] == "player"
