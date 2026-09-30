"""Group conversations (D-48): one scene per round, where everyone in it (and anyone near enough to hear)
may speak in turn; nothing else talks over it."""

import math

import scenes
from test_encounter import face_to_face, post, world  # noqa: F401
from test_intent import walk_near
from test_talk import npc, said, unit_state

import encounter
import minds
import persona
import rounds
import routes_craft
import village
from ai import voice

ROD, BREN, OREN = "npc_roderic_vale", "npc_bren_marr", "npc_oren_dast"


def beside(state, npc_id, dx, dy=0):
    """Someone standing a step or two from the stranger, free to listen."""
    person = npc(state, npc_id)
    person.update(x=state["player"]["x"] + dx, y=state["player"]["y"] + dy)
    minds.mind(person)["job"] = None
    return person


def moment(state, addressed, scripted, text="Look at this needle."):
    """A scene with scripted lines, as rounds.scene would make it."""
    call = {}

    def fake(context, fallback, allowed=True):
        call["context"] = context
        return scenes.scene_call(context, scripted)

    real, voice.scene = voice.scene, fake
    try:
        scene = rounds.scene(state, addressed, text, None, True)
    finally:
        voice.scene = real
    return scene, call["context"]


def test_two_guards_speak_in_one_moment_each_as_themselves():
    state = unit_state()
    face_to_face(state, ROD, reason="talk")
    beside(state, BREN, 2)
    scene, context = moment(state, ROD, [(ROD, said("answer")), (BREN, said("ask_back", impression=1, suspicion=3))])
    people = {p["id"]: p for p in context["people"]}
    assert context["people"][0]["id"] == ROD and BREN in people  # Oren at the gate may hear it too.
    assert people[BREN]["in_the_conversation"].startswith("nearby")
    spoken = rounds.apply_scene(state, scene, "Look at this needle.", None, state["sim_time_ms"])
    assert [s["npc_id"] for s in spoken] == [ROD, BREN]
    assert spoken[1]["trace"]["joined"] and BREN in state["encounter"]["participants"]
    assert encounter.purpose(state["encounter"], BREN) == "joined" and not encounter.hostile(state)
    # Bren's own line changed Bren's own view of the stranger, and he remembers the talk himself.
    assert any(m["kind"] == "talk" for m in npc(state, BREN)["mind"]["memories"])
    assert spoken[1]["trace"]["happened"] and "Roderic just said" in spoken[1]["trace"]["happened"]


def test_only_someone_near_enough_to_hear_can_join():
    state = unit_state()
    face_to_face(state, ROD, reason="talk")
    far = npc(state, OREN)
    far.update(x=state["player"]["x"] + 20, y=state["player"]["y"])
    scene, context = moment(state, ROD, [(ROD, said("answer")), (OREN, said("answer"))])
    assert OREN not in [p["id"] for p in context["people"]]
    spoken = rounds.apply_scene(state, scene, "Hello.", None, state["sim_time_ms"])
    assert [s["npc_id"] for s in spoken] == [ROD] and OREN not in state["encounter"]["participants"]


def test_a_move_a_speaker_may_not_make_is_not_made():
    state = unit_state()
    face_to_face(state, ROD, reason="talk")
    beside(state, BREN, 1)
    scene, _ = moment(state, ROD, [(ROD, said("answer")), (BREN, said("seize"))])
    spoken = rounds.apply_scene(state, scene, "Hello.", None, state["sim_time_ms"])
    assert spoken[1]["key"] != "seize"  # No crime, so no guard may lay hands on the stranger (D-46).
    assert not state.get("arrested")


def test_a_guard_who_comes_to_halt_joins_a_friendly_talk_as_a_listener():
    state = unit_state()
    face_to_face(state, "npc_hessa_marr", reason="talk")
    bren = beside(state, BREN, 2)
    encounter.join(state, bren, "halt", "Halt!", state["sim_time_ms"])
    assert encounter.purpose(state["encounter"], BREN) == "joined" and not encounter.hostile(state)
    assert not any("Halt!" in (e.get("text") or "") for e in state["encounter"]["log"])


def test_no_guard_is_sent_to_halt_someone_already_talking_to_the_captain():
    state = unit_state()
    state["player"].update(x=48, y=16)  # The gate approach, where a guard would come to halt the stranger.
    rod = npc(state, ROD)
    rod.update(x=48, y=15)
    encounter.join(state, rod, "talk", None, state["sim_time_ms"])
    for _ in range(60):
        state["npcs"], _, state["player"] = minds.advance_world(state, 500, state["sim_time_ms"])
        state["sim_time_ms"] += 500
    assert encounter.purpose(state["encounter"], ROD) == "talk" and not encounter.hostile(state)
    assert not any(((g.get("mind") or {}).get("job") or {}).get("then") == "halt" for g in state["npcs"])


def test_nobody_within_earshot_of_the_conversation_wanders_off_into_small_talk():
    state = unit_state()
    face_to_face(state, ROD, reason="talk")
    bren = beside(state, BREN, 2)
    assert not village.free(state, bren)  # Listening, not free: they may join the scene instead.
    state["encounter"] = None
    assert village.free(state, bren)


def test_the_same_two_do_not_make_the_same_small_talk_again_soon():
    state = unit_state()
    state["player"].update(x=5, y=70)  # Far from everyone.
    jory, mara = npc(state, "npc_jory_venn"), npc(state, "npc_mara_venn")
    for person in (jory, mara):
        minds.mind(person).update(job=None, last_met=-(10**9))
        (person.get("controller") or {}).update(activity="idle")
    mara.update(x=jory["x"] + 1, y=jory["y"])
    now = state["sim_time_ms"] + village.MEET_GAP_MS * 2
    village.apply_meeting(state, jory, mara, {}, ("Morning.", "Morning."), now - village.MEET_GAP_MS - 1)
    for person in (jory, mara):
        minds.mind(person)["last_met"] = -(10**9)  # Ready to talk to someone, just not each other.
        minds.mind(person)["chatting_with"] = None
    state["pending_minds"] = []
    village.schedule(state, state["npcs"], now)
    assert not any(p["kind"] == "meet" and p["npc_id"] in (jory["id"], mara["id"]) for p in state["pending_minds"])
    village.schedule(state, state["npcs"], now + village.PAIR_GAP_MS)
    assert any(p["kind"] == "meet" and p["npc_id"] in (jory["id"], mara["id"]) for p in state["pending_minds"])


def test_everyone_knows_who_everyone_else_in_town_is():
    state = unit_state()
    known = persona.voice_sheet(state, npc(state, "npc_kade_east"))["everyone_in_town"]
    assert any(line.startswith("Hessa, the innkeeper") for line in known) and len(known) == len(state["npcs"]) - 1


def test_a_deed_that_names_someone_nearby_is_meant_for_them():
    near = [{"id": ROD, "name": "Roderic"}, {"id": BREN, "name": "Bren"}]
    assert routes_craft.named("I show Rodric the compass", near) == ROD  # Misspelt, still him.
    assert routes_craft.named("I hold the needle up for bren to see", near) == BREN
    assert routes_craft.named("I open the bread", near) is None


def test_showing_someone_a_thing_opens_a_conversation_and_they_answer(world):  # noqa: F811
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    state = walk_near(world, state, "npc_kade_east")
    world.rulings.append(
        {
            "clarifying_question": None,
            "precedent_key": "show",
            "steps": [
                {
                    "action": "other",
                    "outcome": "success",
                    "reason": "You hold up your empty hands.",
                    "effort_seconds": 2,
                    "new_object": None,
                    "take_ids": [],
                    "transformation": None,
                    "harm": None,
                }
            ],
        }
    )
    world.replies.append(said("ask_back"))
    body = post(world, state, "act", {"text": "I show Kade my empty hands"})
    state = body["state"]
    assert body["intent"]["kind"] == "do"
    assert state["encounter"] and "npc_kade_east" in state["encounter"]["participants"]
    assert any(e["kind"] == "reply" for e in state["encounter"]["log"])  # He answers what he was shown.
    assert world.http.get(f"/runs/{state['run_id']}").json() == state  # Replays exactly.
    assert math.isfinite(state["sim_time_ms"])


def test_a_friendly_talk_moves_with_you_but_a_confrontation_holds_you(world):  # noqa: F811
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    state = walk_near(world, state, "npc_kade_east")
    world.replies.append(said("answer"))
    state = post(world, state, "act", {"text": "Good day.", "target_id": "npc_kade_east"})["state"]
    far = next(n for n in state["npcs"] if n["id"] == "npc_elin_west")
    assert math.dist((far["x"], far["y"]), (state["player"]["x"], state["player"]["y"])) > 5
    world.replies.append(said("answer"))
    state = post(world, state, "act", {"text": "Hello there!", "target_id": "npc_elin_west"})["state"]
    assert "npc_elin_west" in state["encounter"]["participants"]  # Walked over to her and she answered.
    assert math.dist((far["x"], far["y"]), (state["player"]["x"], state["player"]["y"])) <= 5
