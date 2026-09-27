"""Arrest instead of death: guards seize, stolen things go back, the stranger is barred for a while; yielding."""
import encounter
import minds
import talk
from test_encounter import face_to_face, play, post, rounds_where, world  # noqa: F401
from test_talk import npc, unit_state


def test_a_seized_stranger_loses_what_they_stole_and_is_marched_off():
    state = unit_state()
    face_to_face(state, "npc_bren_marr", intent="seize", reason="confront")
    state["objects"]["cloth_darin"]["holder_id"] = "player"  # Stolen.
    state["objects"]["lodestone_darin"].update(holder_id="player", lent_to="player")  # Lent: theirs to keep using.
    draft, record = play(state, "wait")
    assert record["seized_by"] == "npc_bren_marr"
    encounter.finish(draft, record, draft["sim_time_ms"])
    assert record["arrested"] and draft["encounter"] is None
    assert draft["objects"]["cloth_darin"]["holder_id"] == "npc_darin_ko"
    assert draft["objects"]["lodestone_darin"]["holder_id"] == "player"
    assert (draft["player"]["x"], draft["player"]["y"]) == encounter.SOUTH_ROAD and draft["player"]["alive"]
    assert talk.barred(draft) and draft["journal"][-1]["kind"] == "arrest"
    roderic = npc(draft, "npc_roderic_vale")
    assert roderic["mind"]["memories"][-1]["kind"] == "arrest"
    assert "admit" not in talk.replies(draft, roderic)  # Not while barred...
    draft["sim_time_ms"] = draft["barred_until"] + 1
    assert "admit" in talk.replies(draft, roderic)  # ...but an arrest isn't the end of the road.


def test_slipping_away_first_beats_a_grab():
    state = unit_state()
    face_to_face(state, "npc_bren_marr", intent="seize", reason="confront")
    state["encounter"]["round"] = rounds_where(state, "player")[0]
    draft, record = play(state, "leave")
    assert record["seized_by"] is None and record["walked_away"]
    assert any(e["kind"] == "seize" and "out of reach" in e["text"] for e in record["entries"])


def test_yielding_stops_a_swing_and_a_guard_takes_you():
    state = unit_state()
    face_to_face(state, "npc_mara_venn", intent="attack", reason="attack")
    draft, record = play(state, "yield")
    assert not any(e["kind"] == "strike" for e in record["entries"])  # She stops mid-swing.
    assert draft["player"].get("health", 100) == 100 and record["seized_by"] is None
    state = unit_state()
    face_to_face(state, "npc_mara_venn", intent="attack", reason="attack")
    bren = npc(state, "npc_bren_marr")
    bren.update(x=state["player"]["x"] + 1, y=state["player"]["y"])
    encounter.join(state, bren, "confront", "Stop there!", state["sim_time_ms"])
    draft, record = play(state, "yield")
    assert record["seized_by"] == "npc_bren_marr"


def test_only_violence_rules_out_entry_for_good():
    state = unit_state()
    roderic = npc(state, "npc_roderic_vale")
    minds.remember(roderic, {"kind": "theft", "severity": 1, "event": 3, "clarity": "clear", "source": "witnessed",
                             "summary": "The stranger took Darin's cloth.", "short": "stole cloth", "victim": None})
    assert "admit" in talk.replies(state, roderic)  # Theft weighs on him; it doesn't bar the stranger forever.
    assert minds.regard(roderic)["suspicion"] > 0.68


def test_only_guards_can_seize():
    state = unit_state()
    hessa = face_to_face(state, "npc_hessa_marr", reason="talk")
    assert "seize" not in {o["action"] for o in encounter.intent_options(state, hessa).values()}
    bren = face_to_face(state, "npc_bren_marr", reason="halt")
    assert "seize" in {o["action"] for o in encounter.intent_options(state, bren).values()}


def test_an_arrest_is_one_round_that_replays(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    cells = [[48, y] for y in range(67, 15, -1)]
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i:i + 20]})["state"]
    for _ in range(60):
        if state.get("encounter"):
            break
        state = post(world, state, "explore", {"elapsed_ms": 1000})["state"]
    state = post(world, state, "encounter/act", {"kind": "wait"})["state"]  # Round 1: the guard asks first.
    world.intents.append("seize")
    body = post(world, state, "encounter/act", {"kind": "wait"})
    state = body["state"]
    assert body["round"]["arrested"] and state["encounter"] is None and state["barred_until"] > state["sim_time_ms"]
    assert (state["player"]["x"], state["player"]["y"]) == encounter.SOUTH_ROAD
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
