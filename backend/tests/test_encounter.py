"""Encounters: rounds with the people who address the stranger (scripted judge and scene, D-48)."""

from types import SimpleNamespace

import pytest
import scenes
from fastapi.testclient import TestClient
from test_craft import attempt, judged
from test_talk import npc, said, unit_state

import app as service
import cast
import clock
import content
import encounter
import tuning
from ai import decider

SOUTH_ROAD = content.MAPS["village"]["after_arrest"]["cell"]  # Where the guards march an arrested stranger.


def face_to_face(state, npc_id, reason="confront"):
    """The stranger beside someone who has come to address them."""
    person = npc(state, npc_id)
    state["player"].update(x=person["x"], y=person["y"] + 1)
    encounter.join(state, person, reason, "You there!", state["sim_time_ms"])
    return person


def blow(target, result="wounded", weapon=None, effort=2):
    return attempt(
        judged(
            "harm",
            effort_seconds=effort,
            harm={
                "target_id": target,
                "weapon_id": weapon,
                "method": "melee",
                "result": result,
                "injury": "a hard blow",
            },
        )
    )


def play(state, kind, text="", judged_result=None, target=None):
    state["event_seq"] += 1
    return encounter.resolve(
        state, "enc00000", {"kind": kind, "text": text, "target_id": target}, judged_result, None, "trace"
    )


def test_people_who_come_to_address_the_stranger_open_an_encounter():
    state = unit_state()
    state["player"].update(x=48, y=16)  # The gate approach: a guard comes to halt the stranger.
    for _ in range(80):
        state["npcs"], _, state["player"] = clock.advance_world(state, 500, state["sim_time_ms"])
        state["sim_time_ms"] += 500
        if state.get("encounter"):
            break
    current = state["encounter"]
    guard = npc(state, current["participants"][0])
    assert current["reason"] == "halt" and cast.card(guard)["guard"] and encounter.hostile(state)
    assert guard["mind"]["job"]["kind"] == "encounter"
    assert current["log"][0]["text"].startswith(guard["name"] + ": “")
    where = (guard["x"], guard["y"])
    state["npcs"], _, _ = clock.advance_world(state, 5_000, state["sim_time_ms"])
    assert (npc(state, guard["id"])["x"], npc(state, guard["id"])["y"]) == where  # Holds still, face to face.


def test_both_act_at_once_a_blow_lands_while_they_are_talking():
    state = unit_state()
    face_to_face(state, "npc_hessa_marr", reason="talk")
    draft, record = play(state, "do", "punch Hessa", blow("npc_hessa_marr"))
    hessa = npc(draft, "npc_hessa_marr")
    assert hessa["health"] < 100 and hessa["alive"]
    assert record["replier"] == "npc_hessa_marr"  # She is addressed, so she answers what just happened...
    assert "Hessa" in " ".join(record["happened"])  # ...which is the blow she just took.
    assert [e["kind"] for e in record["entries"]] == ["do"]


def test_a_blow_at_a_guard_is_a_fight_and_mail_stops_a_fist():
    state = unit_state()
    face_to_face(state, "npc_bren_marr")
    draft, record = play(state, "do", "punch Bren", blow("npc_bren_marr"))
    assert npc(draft, "npc_bren_marr")["health"] == 100  # The armour law: a fist can't hurt through mail.
    assert record["verdict"]["harm"]["result"] == "deflected"
    assert draft["encounter"] is None and "npc_bren_marr" in draft["fight"]["attackers"]  # Words are over.
    assert record["replier"] is None


def test_walking_away_from_a_talk_ends_it():
    calm = unit_state()
    face_to_face(calm, "npc_hessa_marr", reason="talk")
    draft, record = play(calm, "leave")
    encounter.finish(draft, record, draft["sim_time_ms"])
    assert draft["encounter"] is None and record["ended"] and not draft.get("fight")
    assert npc(draft, "npc_hessa_marr")["mind"]["job"]["kind"] != "fight"


def test_someone_who_walks_up_mid_encounter_joins_it():
    state = unit_state()
    face_to_face(state, "npc_hessa_marr", reason="talk")
    bren = npc(state, "npc_bren_marr")
    bren.update(x=state["player"]["x"] + 6, y=state["player"]["y"])
    cast.set_job(
        bren,
        {
            "kind": "approach",
            "target": "player",
            "stop": 2.0,
            "speed": "walk",
            "then": "confront",
            "line": "What's going on here?",
            "line_id": None,
        },
        0,
    )
    state["npcs"], _, _ = clock.advance_world(state, tuning.ROUND_MS, state["sim_time_ms"])
    assert state["encounter"]["participants"] == ["npc_hessa_marr", "npc_bren_marr"]
    assert state["encounter"]["reason"] == "confront"  # No longer just a chat.


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(service.store, "DB_PATH", tmp_path / "enc.sqlite3")
    monkeypatch.setattr(service.attempts, "ASSET_DIR", tmp_path / "assets")
    replies, choices, rulings = [], [], []

    def fake_decide(situation, questions):
        if "impression" in questions:
            return decider.DeciderCall(provider="script", model="script", error="talk is the voice's now (D-46)")
        choice = choices.pop(0) if choices else "listen"  # A scripted reaction: one for everyone, or per person.
        return decider.DeciderCall(
            provider="script",
            model="script",
            answers={
                k: {
                    "type": "choice",
                    "choice": choice.get(k.split("__")[0], "listen") if isinstance(choice, dict) else choice,
                }
                for k in questions
                if k.endswith("action")
            },
        )

    monkeypatch.setattr(service.decider, "decide", fake_decide)
    monkeypatch.setattr(service.decider, "decide_many", lambda requests: [fake_decide(*r) for r in requests])

    def fake_voice(context, fallback, allowed=True):  # The scripted scene (D-48): lines, moves and readings.
        return scenes.scene_call(
            context,
            replies.pop(0) if replies else {},
            lambda ctx, person, move: (
                (person.get("story_beat") or {}).get("get_across")  # Takes a story beat up.
                or f"(voiced) {ctx['what_just_happened'] or ctx['stranger_says']}"[:120]
            ),
        )

    monkeypatch.setattr(service.voice, "scene", fake_voice)
    monkeypatch.setattr(
        service.judge,
        "judge_craft",
        lambda context: service.judge.JudgeCall(status="ok", result=rulings.pop(0), model="stub", attempts=1),
    )
    monkeypatch.setattr(service.attempts, "generate_asset", lambda asset_id: None)
    return SimpleNamespace(http=TestClient(service.app), replies=replies, choices=choices, rulings=rulings)


def post(world, state, path, body, status=200):
    reply = world.http.post(
        f"/runs/{state['run_id']}/{path}",
        json={**body, "expected_version": state["event_seq"], "request_id": f"{path}-{state['event_seq']}"},
    )
    assert reply.status_code == status, reply.text
    return reply.json()


def test_a_halt_becomes_rounds_then_a_shove_is_a_fight_and_giving_up_is_an_arrest(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    cells = [[48, y] for y in range(67, 15, -1)]
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i : i + 20]})["state"]
    for _ in range(60):
        if state.get("encounter"):
            break
        state = post(world, state, "explore", {"elapsed_ms": 1000})["state"]
    guard = state["encounter"]["participants"][0]
    assert post(world, state, "explore", {"elapsed_ms": 1000}, status=409)["detail"]["reason"] == "encounter_active"
    world.replies.append(said("ask_back"))
    body = post(world, state, "encounter/act", {"kind": "say", "text": "Just a traveller, looking for work."})
    state = body["state"]
    assert body["round"]["replier"] == guard and state["encounter"]["round"] == 2
    assert [e["kind"] for e in body["round"]["entries"]] == ["say", "reply"]
    assert body["trace"]["kind"] == "talk"
    assert not any(p["kind"] == "round" for p in state["pending_minds"])  # No second decision per round (D-46).
    assert world.http.get(f"/runs/{state['run_id']}").json() == state  # One event, replayed exactly.
    world.rulings.append(
        blow(guard, "wounded")
    )  # The /craft path during an encounter is the stranger's part of a round.
    world.choices.append("listen")
    reply = world.http.post(
        f"/runs/{state['run_id']}/craft",
        json={
            "text": "shove the guard",
            "selected_ids": [],
            "expected_version": state["event_seq"],
            "request_id": "shove",
        },
    )
    assert reply.status_code == 200, reply.text
    state = reply.json()["state"]
    # A shove at a guard in mail: it does nothing, but it's an assault. Words are over: a real-time fight.
    assert npc(state, guard)["health"] == 100 and state["encounter"] is None and guard in state["fight"]["attackers"]
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
    state = post(world, state, "explore", {"elapsed_ms": 500})["state"]  # The clock runs through a fight.
    body = post(world, state, "act", {"text": "I give up"})
    state = body["state"]
    assert state["fight"] is None and "south road" in body["notice"]  # A guard takes the surrender: arrested.
    assert [state["player"]["x"], state["player"]["y"]] == SOUTH_ROAD and state["barred_until"] > 0
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
    post(world, state, "explore", {"elapsed_ms": 1000})  # The clock runs on.


def test_speaking_to_someone_is_an_encounter_you_can_simply_walk_away_from(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    person = npc(state, "npc_kade_east")
    cells, (x, y) = [], (state["player"]["x"], state["player"]["y"])
    while max(abs(x - person["x"]), abs(y - person["y"] - 1)) > 0:
        x += (person["x"] > x) - (person["x"] < x)
        y += (person["y"] + 1 > y) - (person["y"] + 1 < y)
        cells.append([x, y])
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i : i + 20]})["state"]
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": "npc_kade_east", "text": "Evening."})["state"]
    assert state["encounter"]["reason"] == "talk" and not encounter.hostile(state)
    post(world, state, "move", {"cells": [[state["player"]["x"], state["player"]["y"] + 1]]})  # Not held.
    assert post(world, state, "encounter/act", {"kind": "wait"}, status=409)["detail"]["reason"] == "stale_state"


def test_people_left_behind_drop_out_when_someone_else_joins():
    state = unit_state()
    face_to_face(state, "npc_tomas_reed", reason="talk")
    state["player"].update(x=48, y=15)  # The stranger walked off to the gate...
    guard = npc(state, "npc_bren_marr")
    guard.update(x=48, y=16)
    encounter.join(state, guard, "halt", "Halt!", state["sim_time_ms"])  # ...where a guard stops them.
    encounter.prune(state)
    assert state["encounter"]["participants"] == ["npc_bren_marr"]  # Tomas, back in his yard, isn't in it.


def test_walking_off_ends_a_conversation_and_replays(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    person = npc(state, "npc_kade_east")
    cells, (x, y) = [], (state["player"]["x"], state["player"]["y"])
    while max(abs(x - person["x"]), abs(y - person["y"] - 1)) > 0:
        x += (person["x"] > x) - (person["x"] < x)
        y += (person["y"] + 1 > y) - (person["y"] + 1 < y)
        cells.append([x, y])
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i : i + 20]})["state"]
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": "npc_kade_east", "text": "Evening."})["state"]
    away = [[state["player"]["x"], state["player"]["y"] + n] for n in range(1, 9)]
    state = post(world, state, "move", {"cells": away})["state"]
    assert state["encounter"] is None
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
