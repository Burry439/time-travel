"""A fair baseline (GDD D-46), from the user's own games: favours aren't thefts, grudges can end, guards only arrest
for a real crime not put right, words alone can't sour someone without limit, and no second decision per round."""

from test_craft import commit, judged
from test_encounter import face_to_face, play
from test_talk import npc, said, unit_state

import conversation
import encounter
import perception
import reputation
import talk
import tuning


def rope_theft(state):
    """Tomas's rope, taken; Tomas saw it and told Kade."""
    state["objects"]["rope_tomas"]["holder_id"] = "player"
    for who, source in (("npc_tomas_reed", "victim"), ("npc_kade_east", "told_by:npc_tomas_reed")):
        reputation.remember(
            npc(state, who),
            {
                "kind": "theft",
                "severity": 2,
                "event": 5,
                "clarity": "clear",
                "victim": "npc_tomas_reed",
                "item": "coil of rope",
                "source": source,
                "summary": "The stranger took Tomas's coil of rope.",
                "short": "stole the rope",
            },
        )


def test_fetching_water_from_her_trough_is_not_theft():
    state = unit_state()
    state["player"].update(x=37, y=53)
    state["objects"]["gourd_a"]["holder_id"] = "player"
    commit(state, judged("fill", fill={"container_id": "gourd_a", "source_id": "trough_hessa", "litres": 1.0}))
    seen = perception.perceive(state, state["last_action"])
    assert not any(p["memory"]["kind"] == "theft" for p in seen)  # Using isn't taking.


def test_giving_it_back_settles_it_for_everyone_who_knew():
    state = unit_state()
    rope_theft(state)
    tomas = npc(state, "npc_tomas_reed")
    state["player"].update(x=tomas["x"], y=tomas["y"] + 1)
    commit(state, judged("give", give={"item_ids": ["rope_tomas"], "recipient_id": "npc_tomas_reed"}))
    reputation.after_deed(state, state["last_action"])
    assert reputation.unresolved_crime(npc(state, "npc_tomas_reed")) is None
    assert reputation.unresolved_crime(npc(state, "npc_kade_east")) is None
    assert "seize" not in conversation.moves(state, npc(state, "npc_kade_east"))


def test_an_arrest_answers_for_the_theft():
    state = unit_state()
    rope_theft(state)
    encounter.arrest_player(state, npc(state, "npc_kade_east"), 0)
    assert reputation.unresolved_crime(npc(state, "npc_kade_east")) is None  # Paid for: no second arrest over it.


def test_forgiving_settles_their_own_grudge():
    state = unit_state()
    rope_theft(state)
    tomas = npc(state, "npc_tomas_reed")
    state["player"].update(x=tomas["x"], y=tomas["y"] + 1)
    assert "forgive" in conversation.moves(state, tomas)
    state["event_seq"] = 9
    talk.exchange(
        state, tomas["id"], "I'm sorry. I'll make it right.", said("forgive"), "forgive", "Fine. Let it go.", []
    )
    assert reputation.unresolved_crime(tomas) is None
    assert reputation.unresolved_crime(npc(state, "npc_kade_east")) is not None  # Kade still has his own view.


def test_guards_arrest_or_attack_only_for_a_crime_not_put_right():
    state = unit_state()
    kade = npc(state, "npc_kade_east")
    state["player"].update(x=kade["x"], y=kade["y"] + 1)
    plain = conversation.moves(state, kade)
    assert "seize" not in plain and "attack" not in plain  # Vague answers about family are not a crime.
    rope_theft(state)
    assert {"seize", "attack"} <= set(conversation.moves(state, kade))


def test_walking_off_after_making_amends_is_just_walking_off():
    state = unit_state()
    rope_theft(state)
    reputation.settle(state, "given back", item="coil of rope")
    face_to_face(state, "npc_tomas_reed", reason="talk")
    draft, record = play(state, "leave")
    assert not draft.get("fight") and not any(e["kind"] == "shout_for_help" for e in record["entries"])


def test_words_alone_sour_someone_only_so_far():
    state = unit_state()
    oren = npc(state, "npc_oren_dast")
    start = dict(reputation.regard(oren))
    for _ in range(20):  # Vague, suspicious-sounding answers, over and over.
        talk.update_regard(oren, said("answer", impression=0, suspicion=4))
    assert reputation.regard(oren)["suspicion"] <= start["suspicion"] + tuning.TALK_ILLWILL + 1e-9


def test_no_second_decision_per_round():
    state = unit_state()
    face_to_face(state, "npc_oren_dast", reason="halt")
    draft, record = play(state, "say", "I'm here to visit family.", target="npc_oren_dast")
    encounter.finish(draft, record, draft["sim_time_ms"])
    assert not any(p["kind"] == "round" for p in draft.get("pending_minds", []))
    assert "intents" not in draft["encounter"]  # Nobody commits to anything before hearing the stranger.
