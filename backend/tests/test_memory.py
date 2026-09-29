"""Memory that lasts (GDD D-36): each exchange leaves a note, a name the stranger actually said, doubted
claims; a finished conversation becomes an episode in the thinking lane; old episodes fold into long
memory; and all of it reaches both the decider and the voice the next time you talk. Replays exactly."""
import persona
import talk
from ai import voice
from test_encounter import post, world  # noqa: F401
from test_intent import walk_near
from test_talk import npc, said, unit_state


def speaking(monkeypatch, remember="", name=""):
    monkeypatch.setattr(voice, "converse", lambda context, fallback, allowed=True: voice.VoiceCall(
        status="ok", text="Well met.", model="fake", remember=remember, stranger_name=name, move="answer"))


def test_a_name_is_only_learned_when_the_stranger_said_it():
    state = unit_state()
    talk.exchange(state, "npc_hessa_marr", "I'm Ash, a healer from the south.", said("answer"), "answer",
                  "Welcome, love.", [], note="Ash says he's a healer from the south.", name_given="Ash")
    hessa = npc(state, "npc_hessa_marr")
    assert persona.knows(hessa)["name"] == "Ash" and persona.knows(hessa)["notes"] == ["Ash says he's a healer from the south."]
    talk.exchange(state, "npc_bren_marr", "Just passing through.", said("answer"), "answer", "Hm.", [],
                  name_given="Bob")  # Invented by the model: not in the stranger's words.
    bren = npc(state, "npc_bren_marr")
    assert persona.knows(bren)["name"] is None and "Just passing through" in persona.knows(bren)["notes"][0]
    talk.exchange(state, "npc_bren_marr", "I'm the king's own cousin.", said("answer", believes=0.1), "answer",
                  "Course you are.", [])
    assert persona.knows(bren)["claims"][-1]["text"] == "I'm the king's own cousin."
    situation, _ = talk.request(state, bren, "Well?")
    assert "didn't believe it" in situation and "king's own cousin" in situation


def test_a_finished_conversation_becomes_an_episode_both_models_see(world, monkeypatch):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    state = walk_near(world, state, "npc_kade_east")
    speaking(monkeypatch, remember="Ash says he's a smith looking for work.", name="Ash")
    world.replies.append(said("answer"))
    state = post(world, state, "act", {"text": "“I'm Ash, a smith looking for work.”",
                                       "target_id": "npc_kade_east"})["state"]
    kade = npc(state, "npc_kade_east")
    assert persona.knows(kade)["name"] == "Ash" and persona.knows(kade)["notes"]
    state = post(world, state, "act", {"text": "I walk away"})["state"]
    assert {"npc_id": "npc_kade_east", "kind": "recollect", "why": "the conversation ended"} in state["pending_minds"]
    state = post(world, state, "think", {})["state"]  # Stub mode: the notes themselves become the episode.
    known = persona.knows(npc(state, "npc_kade_east"))
    assert known["notes"] == [] and known["talks"] == 1 and "smith looking for work" in known["episodes"][0]["text"]
    assert world.http.get(f"/runs/{state['run_id']}").json() == state  # Replays exactly.
    kade = npc(state, "npc_kade_east")
    situation, _ = talk.request(state, kade, "Remember me?")
    assert "Ash" in situation and "An earlier conversation" in situation and "new conversation" in situation
    context = talk.voice_context(state, kade, "Remember me?", "answer")
    assert any("Ash" in line for line in context["remembers_the_stranger"]) and context["conversation_so_far"] == []


def test_old_episodes_fold_into_long_memory(world, monkeypatch):
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    known = persona.knows(hessa)
    known["episodes"] = [{"at": i, "text": f"Talk number {i}."} for i in range(persona.EPISODES_KEPT)]
    known["notes"] = ["The stranger brought water."]
    import routes_minds
    context, fallback = routes_minds._recollect_context(hessa)
    assert context["to_fold"] == ["Talk number 0."]
    routes_minds._apply_recollection(hessa, context, fallback, 999)
    assert len(known["episodes"]) == persona.EPISODES_KEPT and "Talk number 0." in known["long_memory"]
    assert known["episodes"][-1]["text"] == "The stranger brought water."
