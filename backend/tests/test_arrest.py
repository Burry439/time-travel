"""Arrest instead of death: guards seize, stolen things go back, the stranger is barred for a while; yielding."""

from test_encounter import face_to_face, play, post, world  # noqa: F401
from test_talk import npc, unit_state

import combat
import conversation
import encounter
import gatekeeping
import reputation


def test_a_seized_stranger_loses_what_they_stole_and_is_marched_off():
    state = unit_state()
    face_to_face(state, "npc_bren_marr", reason="confront")
    state["objects"]["cloth_darin"]["holder_id"] = "player"  # Stolen.
    state["objects"]["lodestone_darin"].update(holder_id="player", lent_to="player")  # Lent: theirs to keep using.
    draft, record = play(state, "yield")  # Giving up to a guard: he takes the stranger.
    assert record["seized_by"] == "npc_bren_marr"
    encounter.finish(draft, record, draft["sim_time_ms"])
    assert record["arrested"] and draft["encounter"] is None
    assert draft["objects"]["cloth_darin"]["holder_id"] == "npc_darin_ko"
    assert draft["objects"]["lodestone_darin"]["holder_id"] == "player"
    assert (draft["player"]["x"], draft["player"]["y"]) == encounter.SOUTH_ROAD and draft["player"]["alive"]
    assert gatekeeping.barred(draft) and draft["journal"][-1]["kind"] == "arrest"
    roderic = npc(draft, "npc_roderic_vale")
    assert roderic["mind"]["memories"][-1]["kind"] == "arrest"
    assert "admit" not in conversation.replies(draft, roderic)  # Not while barred...
    draft["sim_time_ms"] = draft["barred_until"] + 1
    assert "admit" in conversation.replies(draft, roderic)  # ...but an arrest isn't the end of the road.


def test_walking_off_from_someone_you_wronged():
    state = unit_state()
    kade = face_to_face(state, "npc_kade_east", reason="confront")
    reputation.remember(
        kade,
        {
            "kind": "theft",
            "severity": 2,
            "event": 5,
            "clarity": "told",
            "victim": "npc_tomas_reed",
            "item": "coil of rope",
            "source": "told_by:npc_tomas_reed",
            "summary": "Tomas told them: The stranger took Tomas's coil of rope without asking.",
            "short": "stole Tomas's coil of rope",
        },
    )
    draft, _ = play(state, "leave")
    assert "npc_kade_east" in draft["fight"]["attackers"]  # A guard who came about a theft gives chase.
    state = unit_state()
    tomas = face_to_face(state, "npc_tomas_reed", reason="confront")
    reputation.remember(
        tomas,
        {
            "kind": "theft",
            "severity": 2,
            "event": 5,
            "clarity": "clear",
            "victim": "npc_tomas_reed",
            "item": "coil of rope",
            "source": "victim",
            "summary": "The stranger took my coil of rope.",
            "short": "stole my coil of rope",
        },
    )
    draft, record = play(state, "leave")
    assert not draft.get("fight") and any(e["kind"] == "shout_for_help" for e in record["entries"])  # He shouts.
    calm = unit_state()
    face_to_face(calm, "npc_bren_marr", reason="halt")
    draft, _ = play(calm, "leave")
    assert not draft.get("fight")  # A plain halt, nothing held against you: you may walk off.


def test_giving_up_a_fight_a_guard_takes_you_otherwise_they_let_you_be():
    state = unit_state()
    mara = npc(state, "npc_mara_venn")
    state["player"].update(x=mara["x"], y=mara["y"] + 1)
    combat.start(state, ["npc_mara_venn"], 0, "test")
    outcome = encounter.surrender(state, 0)
    assert not outcome["arrested"] and state["fight"] is None and state["player"].get("health", 100) == 100
    assert npc(state, "npc_mara_venn")["mind"]["job"]["kind"] == "watch"
    state = unit_state()
    state["objects"]["cloth_darin"]["holder_id"] = "player"
    combat.start(state, ["npc_mara_venn", "npc_bren_marr"], 0, "test")
    outcome = encounter.surrender(state, 0)
    assert outcome["arrested"] and "Bren" in outcome["text"] and state["fight"] is None
    assert state["objects"]["cloth_darin"]["holder_id"] == "npc_darin_ko" and gatekeeping.barred(state)


def test_only_violence_rules_out_entry_for_good():
    state = unit_state()
    roderic = npc(state, "npc_roderic_vale")
    reputation.remember(
        roderic,
        {
            "kind": "theft",
            "severity": 1,
            "event": 3,
            "clarity": "clear",
            "source": "witnessed",
            "summary": "The stranger took Darin's cloth.",
            "short": "stole cloth",
            "victim": None,
        },
    )
    assert "admit" in conversation.replies(state, roderic)  # Theft weighs on him; it doesn't bar the stranger forever.
    assert reputation.regard(roderic)["suspicion"] > 0.68


def test_giving_up_to_a_guard_is_an_arrest_in_one_round_that_replays(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    cells = [[48, y] for y in range(67, 15, -1)]
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i : i + 20]})["state"]
    for _ in range(60):
        if state.get("encounter"):
            break
        state = post(world, state, "explore", {"elapsed_ms": 1000})["state"]
    state = post(world, state, "encounter/act", {"kind": "wait"})["state"]  # Round 1: the guard asks first.
    body = post(world, state, "encounter/act", {"kind": "yield"})  # Giving up to a guard: arrested.
    state = body["state"]
    assert body["round"]["arrested"] and state["encounter"] is None and state["barred_until"] > state["sim_time_ms"]
    assert (state["player"]["x"], state["player"]["y"]) == encounter.SOUTH_ROAD
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
