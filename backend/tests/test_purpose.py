"""Conversations led by the voice, with purpose (GDD D-44, D-46): the voice reads the moment, says what the person
would say and picks their move, code applies it. People who came about stolen goods deal with the stolen goods;
guards chasing a thief subdue and arrest rather than kill."""
import combat
import encounter
import minds
import store
import talk
from test_encounter import post, world  # noqa: F401
from test_intent import walk_near
from test_talk import npc, said, unit_state


def rope_stolen(state, holder="player"):
    state["objects"]["rope_tomas"].update(holder_id=holder)
    kade = npc(state, "npc_kade_east")
    minds.remember(kade, {"kind": "theft", "severity": 2, "event": 5, "clarity": "told", "victim": "npc_tomas_reed",
                          "item": "coil of rope", "source": "told_by:npc_tomas_reed", "at": 0,
                          "summary": "Tomas told them: The stranger took Tomas's coil of rope without asking.",
                          "short": "stole Tomas's coil of rope"})
    state["player"].update(x=kade["x"], y=kade["y"] + 1)
    return kade


def test_a_guard_who_heard_of_a_theft_can_demand_it_back_take_it_or_arrest():
    state = unit_state()
    kade = rope_stolen(state)
    moves = talk.moves(state, kade, {})
    assert {"demand:rope_tomas", "take_back:rope_tomas", "seize", "attack"} <= set(moves)
    assert "not to kill" in moves["attack"]  # A theft: to subdue.
    context = talk.converse_context(state, kade, "I'm sorry, I won't do it again.", {})
    assert "coil of rope" in context["why_they_are_here"] and "carrying it openly" in context["why_they_are_here"]
    state["event_seq"] = 7
    talk.exchange(state, kade["id"], "I'm sorry.", said("take_back:rope_tomas"), "take_back:rope_tomas",
                  "I'll have that.", [])
    rope = state["objects"]["rope_tomas"]
    assert rope["holder_id"] == "npc_kade_east" and rope["owner_id"] == "npc_tomas_reed"
    assert "take_back:rope_tomas" not in talk.moves(state, kade, {})  # Nothing left to take back.


def test_hessa_only_sees_her_own_things_and_nobody_offers_to_take_what_isnt_theirs():
    state = unit_state()
    state["objects"]["rope_tomas"]["holder_id"] = "player"
    hessa = npc(state, "npc_hessa_marr")
    state["player"].update(x=hessa["x"], y=hessa["y"] + 1)
    moves = talk.moves(state, hessa, {})
    assert not any(k.startswith(("demand:", "take_back:", "seize")) for k in moves) and "attack" not in moves


def test_no_crime_no_arrest(world):
    """A guard may only arrest for a real crime not put right (D-46): with none, a scripted arrest is just talk."""
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    state = walk_near(world, state, "npc_kade_east")
    assert "seize" not in talk.moves(state, npc(state, "npc_kade_east"))
    world.replies.append(said("seize"))
    body = post(world, state, "act", {"text": "What are you looking at?", "target_id": "npc_kade_east"})
    assert not body["round"].get("arrested") and body["state"]["encounter"] is not None
    assert world.http.get(f"/runs/{body['state']['run_id']}").json() == body["state"]


def test_subdued_on_the_clock_means_arrested_not_dead_and_it_replays():
    state = unit_state()
    kade = rope_stolen(state)
    state["objects"]["rope_tomas"]["holder_id"] = "player"
    combat.start(state, [kade["id"]], 0, "chase")
    assert state["fight"]["lethal"][kade["id"]] is False
    for _ in range(60):
        payload = store.advance_people(state, 500)
        state["sim_time_ms"] += 500
        state["npcs"] = payload["npcs"]
        store.apply_people(state, payload)
        if not state.get("fight"):
            break
    assert state["player"]["alive"] and state["player"]["health"] == combat.SUBDUED_AT
    assert (state["player"]["x"], state["player"]["y"]) == encounter.SOUTH_ROAD and talk.barred(state)
    assert state["objects"]["rope_tomas"]["holder_id"] == "npc_tomas_reed"  # The rope goes back.
    assert any(e.get("kind") == "arrest" for e in state["journal"])
