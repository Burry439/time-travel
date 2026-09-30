"""The tutorial, "The first morning" (D-50, D-52): linear, card by card; outcomes, not recipes; the bout; the
device; exact replay."""

import pytest
from test_encounter import post, world  # noqa: F401

import app as service
import combat
import gear
import minds
import tutorial
import village


@pytest.fixture(autouse=True)
def quiet_village(monkeypatch):
    monkeypatch.setattr(village, "schedule", lambda state, npcs, now: None)


def tutorial_state():
    return service.initial_state(
        {
            "id": "tut00000",
            "mode": "developer",
            "seed_version": service.SEED_VERSION,
            "geometry_version": service.GEOMETRY_VERSION,
            "scenario": "tutorial",
        }
    )


def npc(state, npc_id):
    return minds.find(state["npcs"], npc_id)


def at_step(state):
    return tutorial.STEPS[state["tutorial"]["step"]]["id"] if tutorial.active(state) else "done"


def carry(state, oid, **fields):
    obj = state["objects"][oid]
    obj.update(holder_id="player", **fields)
    return obj


def read_and_tick(state):
    """The player presses through the step's cards; then the clock beat checks it."""
    tutorial.read_cards(state)
    return tutorial.tick(state)


def beat(state, ms=500):
    state["npcs"], heard, state["player"] = minds.advance_world(state, ms, state["sim_time_ms"])
    for object_id, fields in state.pop("people_objects_changed", {}).items():
        state["objects"][object_id].update(fields)
    state.pop("people_objects_added", None)
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)


def test_a_tutorial_journey_starts_with_the_device_and_kades_practice_gear():
    state = tutorial_state()
    assert state["scenario"] == "tutorial" and at_step(state) == "welcome" and state["tutorial"]["read"] == -1
    assert state["device_log"] and "device" in state["device_log"][0]["text"]
    assert state["objects"]["practice_sword"]["holder_id"] == "npc_kade_east"
    assert state["objects"]["steel_file"]["holder_id"] is None  # Lying by the smithy, anyone's to take.
    village_run = service.initial_state(
        {
            "id": "vil00000",
            "mode": "developer",
            "seed_version": service.SEED_VERSION,
            "geometry_version": service.GEOMETRY_VERSION,
        }
    )
    assert "tutorial" not in village_run and "practice_sword" not in village_run["objects"]


def test_nothing_counts_until_the_cards_are_read_and_it_is_one_step_at_a_time():
    """D-52: the welcome ('always') waits for its cards; a player already standing in the ring and carrying
    everything still sees every step's cards: each step completes only once its own cards are read."""
    state = tutorial_state()
    state["player"].update(x=48, y=62)
    carry(state, "plantain_a")
    assert not tutorial.tick(state) and at_step(state) == "welcome"
    assert read_and_tick(state) and at_step(state) == "walk"
    assert not tutorial.tick(state) and at_step(state) == "walk"  # In the ring already, but its cards come first.
    assert read_and_tick(state) and at_step(state) == "look"
    tutorial.ui_done(state, "inspect")
    read_and_tick(state)
    assert at_step(state) == "take"  # Never two steps in one tick.
    read_and_tick(state)
    assert at_step(state) == "gather"


def test_the_whole_story_moves_on_by_outcomes():
    state = tutorial_state()
    read_and_tick(state)  # welcome
    state["player"].update(x=48, y=62)
    read_and_tick(state)
    tutorial.ui_done(state, "inspect")
    read_and_tick(state)
    carry(state, "plantain_a")
    read_and_tick(state)
    carry(state, "flint_a")
    read_and_tick(state)
    assert at_step(state) == "gather"  # The dry grass too.
    carry(state, "grass_a")
    read_and_tick(state)
    assert at_step(state) == "pack"
    tutorial.ui_done(state, "pack")
    read_and_tick(state)
    assert at_step(state) == "smithy"
    jory = npc(state, "npc_jory_venn")
    assert any(c["kind"] == "burn" for c in jory["conditions"])  # His cry, and his burn.
    state["player"].update(x=jory["x"], y=jory["y"] + 1)
    read_and_tick(state)
    assert at_step(state) == "talk"
    minds.mind(jory).setdefault("talk", []).append({"who": "stranger", "text": "Let me see your arm.", "at": 0})
    read_and_tick(state)
    assert at_step(state) == "remedy"
    poultice = state["objects"]["plantain_a"]
    poultice["gear"] = {"kind": "remedy", "class": "poultice", "covers": [], "quality": "fair"}
    read_and_tick(state)
    assert at_step(state) == "treat"
    burn = next(i for i, c in enumerate(jory["conditions"]) if c["kind"] == "burn")
    assert gear.treat(jory, burn, poultice, state["sim_time_ms"])["ok"]
    read_and_tick(state)
    assert at_step(state) == "kade"
    mara, kade = npc(state, "npc_mara_venn"), npc(state, "npc_kade_east")
    assert mara["mind"]["job"]["kind"] == "tell" and mara["mind"]["job"]["target"] == "npc_kade_east"  # She goes.
    read_and_tick(state)
    held_while_told = None
    for _ in range(120):  # She walks over and tells him; then they come (D-53: people pass things on).
        beat(state, 1000)
        tutorial.tick(state)
        kade = npc(state, "npc_kade_east")
        if held_while_told is None and "kade:reply" in state["tutorial"]["fired"]:
            held_while_told = ((kade.get("mind") or {}).get("job") or {}).get("kind")
        if ((kade.get("mind") or {}).get("job") or {}).get("kind") == "approach":
            break
    assert any(h["from"] == "npc_mara_venn" for h in kade["mind"]["knows"]["heard"])
    assert held_while_told == "watch"  # He hears her out before he goes (D-57): nobody walks off mid-word.
    assert kade["mind"]["job"]["kind"] == "approach" and "kade:called" in state["tutorial"]["fired"]
    assert npc(state, "npc_mara_venn")["mind"]["job"]["kind"] == "approach"  # She comes back with him.
    kade.update(x=state["player"]["x"] + 1, y=state["player"]["y"])
    read_and_tick(state)
    assert state["objects"]["practice_sword"]["lent_to"] == "player" and at_step(state) == "arm"  # Lent, not stolen.
    assert kade["mind"]["job"]["kind"] == "watch"  # He stays for his lessons (D-57).
    assert gear.equip(state, state["player"], state["objects"]["practice_sword"], "right")["ok"]
    read_and_tick(state)
    assert at_step(state) == "arm"  # The shield too: one hand each (D-57).
    assert gear.equip(state, state["player"], state["objects"]["wicker_shield"], "left")["ok"]
    assert state["player"]["equipped"]["right"] == "practice_sword"  # The sword stays in hand.
    read_and_tick(state)
    assert at_step(state) == "bout" and not state.get("fight")  # The bout waits for its cards...
    read_and_tick(state)
    assert state["fight"] and state["fight"]["spar"]  # ...then, armed and beside him, it begins.
    assert not combat.surrender(state, state["sim_time_ms"])["arrested"] and state["fight"] is None
    tutorial.tick(state)
    assert at_step(state) == "why" and "doing on this road" in kade["mind"]["said"]["text"]
    read_and_tick(state)
    assert at_step(state) == "why"  # Nothing said to him yet this step.
    state["sim_time_ms"] += 1000
    minds.mind(kade).setdefault("talk", []).append(
        {"who": "stranger", "text": "I'm trying to get into the city.", "at": state["sim_time_ms"]}
    )
    read_and_tick(state)
    assert at_step(state) == "steel"
    carry(state, "steel_file")
    read_and_tick(state)
    assert at_step(state) == "fire"
    tutorial.read_cards(state)
    # A thing made earlier in front of someone (the poultice) isn't the fire (seen in play, 30 Sep 2026).
    assert not tutorial.tick(state) and at_step(state) == "fire"
    state["event_seq"] = state["tutorial"]["started_seq"] + 3
    state["objects"]["fire_made"] = {
        "id": "fire_made",
        "name": "small fire",
        "created_by": "player",
        "created_event_id": state["event_seq"],
        "flags": ["heat_source", "light_source"],
        "holder_id": None,
        "x": state["player"]["x"],
        "y": state["player"]["y"],
    }
    minds.remember(
        kade,
        {
            "kind": "demonstration",
            "works": True,
            "clarity": "clear",
            "severity": 1,
            "event": 99,
            "at": state["sim_time_ms"],
            "item": "small fire",
            "summary": "The stranger made a fire.",
            "short": "made a small fire",
            "victim": None,
            "source": "witnessed",
        },
    )
    tutorial.tick(state)
    assert at_step(state) == "captain" and state["tutorial"]["flags"]["wants_in"]
    assert kade["mind"]["job"]["kind"] == "vouch" and "want to come into the city" in kade["mind"]["job"]["why"]
    read_and_tick(state)
    for _ in range(300):  # Kade walks to the gate and speaks; Roderic, who now knows they want in, comes over.
        beat(state, 1000)
        tutorial.tick(state)
        if state.get("admitted"):
            break
    roderic = npc(state, "npc_roderic_vale")  # A beat brings everyone's latest record.
    assert any(m["kind"] == "vouch" and m.get("by") == "npc_kade_east" for m in roderic["mind"]["memories"])
    assert "captain:comes" in state["tutorial"]["fired"] and state["admitted"]["by"] == "npc_roderic_vale"
    assert state["gate_open"] and any("Kade" in reason for reason in state["admitted"]["because"])
    assert at_step(state) == "city"
    read_and_tick(state)
    assert at_step(state) == "done" and state["objective"] == "Get inside the city"
    assert "up to you" in " ".join(line["text"] for line in state["device_log"])


def at_captain(told_kade: str):
    """The story at its last task, Kade's word given to the captain after hearing this from the stranger."""
    state = tutorial_state()
    state["tutorial"]["step"] = next(i for i, s in enumerate(tutorial.STEPS) if s["id"] == "fire")
    kade = npc(state, "npc_kade_east")
    minds.mind(kade).setdefault("talk", []).append({"who": "stranger", "text": told_kade, "at": 0})
    tutorial._do(state, [{"kind": "vouch", "npc": "npc_kade_east"}], 0)
    state["tutorial"]["step"] += 1
    state["tutorial"]["read"] = state["tutorial"]["step"]
    return state, kade


def test_the_captain_needs_asking_if_nobody_told_him_the_stranger_wants_in():
    """D-57: Kade tells Roderic what he saw. Only if the stranger told Kade they want to come into the city does
    Roderic know it, and come to let them in himself; otherwise the stranger has to ask, and Kade's word is the
    grounds his yes needs."""
    import talk

    state, kade = at_captain("Just passing through, looking for work.")
    assert not state["tutorial"]["flags"]["wants_in"] and "want to come" not in kade["mind"]["job"]["why"]
    roderic = npc(state, "npc_roderic_vale")
    assert "admit" not in talk.moves(state, roderic)  # Nothing to go on yet.
    for _ in range(120):
        beat(state, 1000)
        tutorial.tick(state)
        roderic = npc(state, "npc_roderic_vale")
        if any(m["kind"] == "vouch" for m in (roderic.get("mind") or {}).get("memories", [])):
            break
    tutorial.tick(state)
    assert "captain:comes" not in state["tutorial"]["fired"] and not state.get("admitted")
    assert "admit" in talk.moves(state, roderic)  # Asked, he may: Kade's word is something real to go on.
    state, _ = at_captain("I want to get inside the city walls.")
    assert state["tutorial"]["flags"]["wants_in"]


def test_kade_stays_for_his_lessons_and_does_not_let_them_in_himself():
    import talk

    state = tutorial_state()
    kade = npc(state, "npc_kade_east")
    state["tutorial"]["step"] = next(i for i, s in enumerate(tutorial.STEPS) if s["id"] == "why")
    assert tutorial.keeps(state, kade)
    moves = talk.replies(state, kade)
    assert not any(o["act"] in ("go_tell", "vouch", "call_guard", "admit") for o in moves.values())
    state["tutorial"]["fired"].append("kade:lent")  # He has come over.
    minds._set_job(kade, {"kind": "watch", "until": 20_000}, 0)  # What a talk leaves him with...
    assert tutorial.tick(state) and kade["mind"]["job"]["until"] >= 600_000  # ...renewed: he stays for his lessons.
    state["tutorial"]["step"] = next(i for i, s in enumerate(tutorial.STEPS) if s["id"] == "captain")
    assert not tutorial.keeps(state, kade)


def test_an_older_tutorial_journey_simply_carries_on_as_a_journey():
    state = tutorial_state()
    state["tutorial"]["version"] = 2  # Its steps no longer line up with the story.
    assert not tutorial.active(state) and not tutorial.tick(state)


def test_every_step_is_well_formed():
    for step in tutorial.STEPS:
        assert step["cards"] and all(isinstance(c, str) and c for c in step["cards"]), step["id"]
        if step["check"]["kind"] != "always":
            assert step["task"] and step.get("help"), step["id"]
        if step.get("suggest"):
            assert step["suggest"]["text"] and "button" in step["suggest"], step["id"]
        focus = step.get("focus") or {}
        for oid in [focus.get("object")] + focus.get("objects", []):
            assert oid is None or oid in tutorial_state()["objects"], (step["id"], oid)


def test_the_bout_is_practice_no_crime_no_blood_no_arrest():
    state = tutorial_state()
    kade = npc(state, "npc_kade_east")
    state["player"].update(x=48, y=60)
    kade.update(x=49, y=60)
    sword = carry(state, "practice_sword")
    gear.equip(state, state["player"], sword, "right")
    tutorial._do(state, [{"kind": "spar", "npc": "npc_kade_east"}], 0)
    assert state["fight"]["spar"] and gear.held(state, kade, "right")["id"] == "practice_sword_kade"
    for _ in range(40):
        if not state["fight"]:
            break
        kade.update(x=49, y=60)
        combat.strike(state, "right", "npc_kade_east", state["sim_time_ms"])
        beat(state)
    outcomes = [
        e["category"]
        for e in state["journal"]
        if e.get("kind") == "fight" and e.get("category") in tutorial.SPAR_OUTCOMES
    ]
    assert outcomes and state["fight"] is None
    assert not state.get("barred_until") and not state.get("subdued_by")  # Nobody arrests anybody.
    assert not kade.get("conditions") and not state["player"].get("conditions")  # Pulled blows: nobody bleeds.
    assert kade.get("alive", True) and not kade.get("down")
    assert state["player"].get("health", 100) == 100 and npc(state, "npc_kade_east").get("health", 100) == 100  # Faded.
    assert not any(m["kind"] == "violence" for n in state["npcs"] for m in (n.get("mind") or {}).get("memories", []))


def test_the_device_reacts_once_to_something_drastic_even_mid_cards():
    state = tutorial_state()
    npc(state, "npc_darin_ko")["alive"] = False
    assert tutorial.tick(state)
    lines = [line["text"] for line in state["device_log"] if line["kind"] == "reaction"]
    assert len(lines) == 1 and "killed" in lines[0]
    tutorial.tick(state)
    assert len([line for line in state["device_log"] if line["kind"] == "reaction"]) == 1


def test_the_device_knows_only_what_the_stranger_does():
    state = tutorial_state()
    read_and_tick(state)
    context = tutorial.device_context(state, "What is Oren hiding?")
    flat = str(context)
    assert "secrets" not in flat and "late shifts" not in flat  # Bren's secret about Oren is nowhere in it.
    assert context["tutorial"] and context["step"]["title"] == "Walking" and "Space" in context["controls"]
    assert tutorial.fallback_answer(state) == tutorial.STEPS[1]["help"][0]


# --- Over HTTP ------------------------------------------------------------------------------------------------


def test_a_tutorial_journey_over_http_reads_progresses_asks_and_replays(world):
    http = world.http
    state = http.post("/runs", json={"mode": "developer", "scenario": "tutorial"}).json()
    run = f"/runs/{state['run_id']}"
    assert state["scenario"] == "tutorial" and state["tutorial"]["step"] == 0
    state = http.post(f"{run}/tutorial/read", json={"step": 0}).json()["state"]
    assert state["tutorial"]["step"] == 1 and state["tutorial"]["read"] == 0  # Welcome read: on to walking.
    state = http.post(f"{run}/tutorial/read", json={"step": 1}).json()["state"]
    cells = [[48, y] for y in range(67, 61, -1)]
    state = post(world, state, "move", {"cells": cells})["state"]
    state = post(world, state, "explore", {"elapsed_ms": 500})["state"]  # The clock beat checks the story.
    assert state["tutorial"]["step"] == 2
    state = http.post(f"{run}/tutorial/read", json={"step": 2}).json()["state"]
    assert http.post(f"{run}/tutorial/ui", json={"key": "teleport"}).status_code == 422
    state = http.post(f"{run}/tutorial/ui", json={"key": "inspect"}).json()["state"]
    assert state["tutorial"]["step"] == 3 and "inspect" in state["tutorial"]["ui_done"]
    body = post(world, state, "device/ask", {"question": "What should I do?"})
    assert body["answer"] == tutorial.STEPS[3]["help"][0]  # No model in tests: the step's written help.
    state = body["state"]
    assert state["journal"][-1]["kind"] == "device" and state["journal"][-1]["question"] == "What should I do?"
    skipped = http.post(f"{run}/tutorial/skip").json()["state"]
    assert skipped["tutorial"]["step"] == 4 and skipped["objective"] == tutorial.STEPS[4]["task"]
    assert http.get(run).json() == skipped  # Replays exactly.
    normal = http.post("/runs", json={"mode": "normal", "scenario": "tutorial"}).json()
    assert http.post(f"/runs/{normal['run_id']}/tutorial/skip").status_code == 403
    assert http.post("/runs", json={"mode": "normal", "scenario": "moon"}).status_code == 422


def test_a_blow_at_kade_during_his_lessons_is_the_bout_not_an_assault():
    """Seen in play (30 Sep 2026): a punch at Kade with an empty left hand began a real fight, and he killed the
    stranger with his spear. While Kade is teaching, any blow at him starts the practice bout (D-53)."""
    state = tutorial_state()
    state["tutorial"]["step"] = next(i for i, s in enumerate(tutorial.STEPS) if s["id"] == "arm")
    state["tutorial"]["read"] = state["tutorial"]["step"]
    kade = npc(state, "npc_kade_east")
    state["player"].update(x=48, y=60)
    kade.update(x=49, y=60)
    assert combat.strike(state, "left", "npc_kade_east", state["sim_time_ms"])["ok"]  # Bare fists.
    beat(state, 1000)
    assert state["fight"] and state["fight"]["spar"] and state["fight"]["lethal"]["npc_kade_east"] is False
    assert gear.held(state, npc(state, "npc_kade_east"), "right")["id"] == "practice_sword_kade"  # Not his spear.
    assert not any(m["kind"] == "violence" for n in state["npcs"] for m in (n.get("mind") or {}).get("memories", []))
    assert "bout:spar" in state["tutorial"]["fired"]


def test_in_a_bout_blows_reach_only_the_partner_and_a_late_swing_is_checked():
    """Seen in the live playthrough (30 Sep 2026): Mara stood beside the stranger during the bout; a swing still in
    the air as it ended hit her, and Kade fought for real. In a practice bout the stranger's blows are for the
    partner only, and one that lands after it's over is checked (D-57)."""
    state = tutorial_state()
    state["tutorial"]["step"] = next(i for i, s in enumerate(tutorial.STEPS) if s["id"] == "bout")
    state["player"].update(x=48, y=60)
    npc(state, "npc_kade_east").update(x=49, y=60)
    npc(state, "npc_mara_venn").update(x=48, y=61)  # Right in front of the stranger, who faces south.
    gear.equip(state, state["player"], carry(state, "practice_sword"), "right")
    tutorial._do(state, [{"kind": "spar", "npc": "npc_kade_east"}], 0)
    assert combat.strike(state, "right", None, state["sim_time_ms"], [0.0, 1.0])["ok"]
    assert state["player"]["swings"]["right"]["spar_with"] == "npc_kade_east"
    combat.surrender(state, state["sim_time_ms"])  # The bout ends with the blow still winding up.
    for _ in range(3):
        beat(state, 1000)
    mara = npc(state, "npc_mara_venn")
    assert mara.get("health", 100) == 100 and mara.get("alive", True)
    assert any("check your swing" in str(e.get("reason", "")) for e in state["journal"])
    assert not any(m["kind"] == "violence" for n in state["npcs"] for m in (n.get("mind") or {}).get("memories", []))
    assert state["player"].get("alive", True) and not state.get("fight")
