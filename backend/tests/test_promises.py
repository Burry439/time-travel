"""People keep their word (D-51): a promise to go and tell someone is a move that happens, a person who was helped
can speak for the stranger, and a promise the voice made without the move is carried out by code when it can be."""
import minds
import rounds
import talk
from test_talk import npc, unit_state


def advance(state, ms):
    state["npcs"], heard, state["player"] = minds.advance_world(state, ms, state["sim_time_ms"])
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)


def treated(state, npc_id):
    minds.remember(npc(state, npc_id), {"kind": "help", "severity": 1, "victim": npc_id, "item": "poultice",
                                        "event": 7, "clarity": "clear", "source": "received", "at": 0,
                                        "summary": "The stranger treated my burn.", "short": "treated my burn"})


def test_someone_helped_can_speak_for_the_stranger_whatever_their_trust():
    state = unit_state()
    jory = npc(state, "npc_jory_venn")
    talk.regard(jory)["trust"] = 0.3
    assert "vouch" not in talk.replies(state, jory)
    treated(state, "npc_jory_venn")
    talk.regard(jory)["trust"] = 0.3  # Evidence raised it; the help alone must be enough.
    assert "vouch" in talk.replies(state, jory)


def test_go_tell_walks_over_and_the_listener_remembers():
    state = unit_state()
    done = talk.exchange(state, "npc_jory_venn", "Could you tell Mara I'm here?", {}, "go_tell", "I'll tell her now.",
                         [], errand_to="npc_mara_venn", errand_message="The stranger at the smithy wants a word with you.")
    jory = npc(state, "npc_jory_venn")
    assert jory["mind"]["job"]["kind"] == "tell" and done["learned"][-1]["errand"] == "npc_mara_venn"
    for _ in range(120):
        advance(state, 1000)
        if (jory["mind"].get("job") or {}).get("kind") != "tell":
            break
    mara = npc(state, "npc_mara_venn")
    assert any(m["kind"] == "told" and "wants a word" in m["summary"] for m in mara["mind"]["memories"])
    assert mara["mind"]["knows"]["heard"][-1]["from_name"] == "Jory"


def test_an_errand_to_nobody_is_just_talk():
    state = unit_state()
    talk.exchange(state, "npc_jory_venn", "hm", {}, "go_tell", "Right.", [], errand_to="npc_nobody",
                  errand_message="hello")
    assert (npc(state, "npc_jory_venn")["mind"].get("job") or {}).get("kind") != "tell"


def test_a_promise_without_its_move_is_kept_by_code():
    """Jory said he'd go and tell the captain, but the voice picked 'answer' (seen in play, 29 Sep 2026)."""
    state = unit_state()
    jory = npc(state, "npc_jory_venn")
    key, to, message, unkept = rounds.keep_promise(state, jory, "tell Captain Roderic the stranger healed my arm",
                                                   "", "")
    assert (key, to, unkept) == ("go_tell", "npc_roderic_vale", None) and "healed my arm" in message
    key, to, message, unkept = rounds.keep_promise(state, jory, "tell the guards what you did", "", "")
    assert key == "go_tell" and to == "npc_roderic_vale"
    key, _, _, unkept = rounds.keep_promise(state, jory, "think about it overnight", "", "")
    assert key == "answer" and unkept == "think about it overnight"  # Nothing to carry out: noted, not faked.


def test_someone_given_a_remedy_can_put_it_on_themselves():
    """Jory, handed a poultice, can use it on his own burn (D-53); without it he can't pretend to."""
    import gear
    state = unit_state()
    jory = npc(state, "npc_jory_venn")
    gear.add_condition(jory, {"kind": "burn", "area": "arm", "severity": 18}, 0)
    assert not any(k.startswith("treat_self") for k in talk.replies(state, jory))
    context = talk.voice_context(state, jory, "put it on your burn", "answer")
    assert context["what_they_have"] == ["nothing in their hands"]
    poultice = state["objects"]["plantain_a"]
    poultice.update(holder_id="npc_jory_venn", gear={"kind": "remedy", "class": "poultice", "covers": [],
                                                    "quality": "fair"})
    assert "treat_self:plantain_a" in talk.replies(state, jory)
    talk.exchange(state, "npc_jory_venn", "put it on your burn", {}, "treat_self:plantain_a", "There. Cooler.", [])
    burn = next(c for c in npc(state, "npc_jory_venn")["conditions"] if c["kind"] == "burn")
    assert burn["treated"] > 0 and state["objects"]["plantain_a"]["holder_id"] == "used"


def test_good_news_travels_too():
    """Someone who clearly saw the stranger do a kindness may go and tell a friend or a guard (D-53)."""
    import village
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    minds.remember(hessa, {"kind": "help", "severity": 1, "victim": "npc_jory_venn", "item": "poultice", "event": 41,
                           "clarity": "clear", "source": "witnessed", "at": 0,
                           "summary": "The stranger treated Jory's burn with a poultice.", "short": "treated Jory"})
    options = village.agenda_options(state, hessa)
    tells = [k for k, o in options.items() if k.startswith("tell:") and o["plan"]["kind"] == "tell"]
    assert tells
    village.apply_agenda(state, hessa, {"agenda": {"choice": tells[0]}, "tell_someone": {"noul": 0.9}}, 0)
    job = hessa["mind"]["job"]
    assert job["kind"] == "tell" and "Jory's burn" in job["message"] and job["event"] == 41
