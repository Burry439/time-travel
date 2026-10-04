"""People keep their word (D-51): a promise to go and tell someone is a move that happens, a person who was helped
can speak for the stranger, and a promise the voice made without the move is carried out by code when it can be."""

from test_talk import npc, unit_state

import briefing
import clock
import conversation
import perception
import reputation
import rounds
import talk


def advance(state, ms):
    state["npcs"], heard, state["player"] = clock.advance_world(state, ms, state["sim_time_ms"])
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)


def treated(state, npc_id):
    reputation.remember(
        npc(state, npc_id),
        {
            "kind": "help",
            "severity": 1,
            "victim": npc_id,
            "item": "poultice",
            "event": 7,
            "clarity": "clear",
            "source": "received",
            "at": 0,
            "summary": "The stranger treated my burn.",
            "short": "treated my burn",
        },
    )


def test_someone_helped_can_speak_for_the_stranger_whatever_their_trust():
    state = unit_state()
    jory = npc(state, "npc_jory_venn")
    reputation.regard(jory)["trust"] = 0.3
    assert "vouch" in conversation.replies(state, jory)  # Offered whatever their trust (D-62): theirs to decide.
    treated(state, "npc_jory_venn")
    reputation.regard(jory)["trust"] = 0.3  # Evidence raised it; the help alone must be enough.
    assert "vouch" in conversation.replies(state, jory)


def test_go_tell_walks_over_and_the_listener_remembers():
    state = unit_state()
    done = talk.exchange(
        state,
        "npc_jory_venn",
        "Could you tell Mara I'm here?",
        {},
        "go_tell",
        "I'll tell her now.",
        [],
        errand_to="npc_mara_venn",
        errand_message="The stranger at the smithy wants a word with you.",
    )
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
    talk.exchange(
        state, "npc_jory_venn", "hm", {}, "go_tell", "Right.", [], errand_to="npc_nobody", errand_message="hello"
    )
    assert (npc(state, "npc_jory_venn")["mind"].get("job") or {}).get("kind") != "tell"


def test_a_promise_without_its_move_is_kept_by_code():
    """Jory said he'd go and tell the captain, but the voice picked 'answer' (seen in play, 29 Sep 2026)."""
    state = unit_state()
    jory = npc(state, "npc_jory_venn")
    key, to, message, unkept = rounds.keep_promise(
        state, jory, "tell Captain Roderic the stranger healed my arm", "", ""
    )
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
    assert not any(k.startswith("treat_self") for k in conversation.replies(state, jory))
    context = briefing.voice_context(state, jory, "put it on your burn", "answer")
    assert context["what_they_have"] == ["nothing in their hands"]
    poultice = state["objects"]["plantain_a"]
    poultice.update(
        holder_id="npc_jory_venn", gear={"kind": "remedy", "class": "poultice", "covers": [], "quality": "fair"}
    )
    assert "treat_self:plantain_a" in conversation.replies(state, jory)
    talk.exchange(state, "npc_jory_venn", "put it on your burn", {}, "treat_self:plantain_a", "There. Cooler.", [])
    burn = next(c for c in npc(state, "npc_jory_venn")["conditions"] if c["kind"] == "burn")
    assert burn["treated"] > 0 and state["objects"]["plantain_a"]["holder_id"] == "used"


def test_good_news_travels_too():
    """Someone who clearly saw the stranger do a kindness may go and tell a friend or a guard (D-53)."""
    import village

    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    reputation.remember(
        hessa,
        {
            "kind": "help",
            "severity": 1,
            "victim": "npc_jory_venn",
            "item": "poultice",
            "event": 41,
            "clarity": "clear",
            "source": "witnessed",
            "at": 0,
            "summary": "The stranger treated Jory's burn with a poultice.",
            "short": "treated Jory",
        },
    )
    options = village.agenda_options(state, hessa)
    tells = [k for k, o in options.items() if k.startswith("tell:") and o["plan"]["kind"] == "tell"]
    assert tells
    village.apply_agenda(state, hessa, {"agenda": {"choice": tells[0]}, "tell_someone": {"noul": 0.9}}, 0)
    job = hessa["mind"]["job"]
    assert job["kind"] == "tell" and "Jory's burn" in job["message"] and job["event"] == 41


def test_a_word_in_passing_does_not_cancel_an_errand():
    """Seen in play (30 Sep 2026): Jory set off to tell Kade, the stranger spoke to him again, and his reply put him
    back to standing about; Kade never heard. An errand survives a word in passing (D-54)."""
    state = unit_state()
    talk.exchange(
        state,
        "npc_jory_venn",
        "Tell Kade about me?",
        {},
        "go_tell",
        "I'll go now.",
        [],
        errand_to="npc_kade_east",
        errand_message="The stranger knows things worth hearing.",
    )
    talk.exchange(state, "npc_jory_venn", "Was that impressive?", {}, "answer", "It was!", [])
    job = npc(state, "npc_jory_venn")["mind"]["job"]
    assert job["kind"] == "tell" and job["target"] == "npc_kade_east"


def test_watching_something_made_counts_as_being_shown_it():
    """The fire made in front of Jory (not 'shown' in so many words) is still something he saw work (D-54)."""
    state = unit_state()
    jory = npc(state, "npc_jory_venn")
    state["player"].update(x=jory["x"], y=jory["y"] + 1)
    entry = {
        "event_id": 88,
        "category": "success",
        "action": "make",
        "made_ids": ["made_88"],
        "made_name": "small fire",
        "reason": "Sparks catch in the dry grass.",
        "property": [],
    }
    perception.apply_perceptions(state, perception.perceive(state, entry))
    seen = [m for m in npc(state, "npc_jory_venn")["mind"]["memories"] if m["kind"] == "demonstration"]
    assert seen and seen[-1]["clarity"] == "clear" and "small fire" in seen[-1]["summary"]


def test_arriving_with_news_stops_them_both_and_the_listener_reacts():
    """D-54: on arrival the two stop and talk; the voice words both lines and picks what the listener does, from
    options code built; code carries it out (here Kade goes to see the stranger)."""
    import village

    state = unit_state()
    talk.exchange(
        state,
        "npc_jory_venn",
        "Tell Kade?",
        {},
        "go_tell",
        "I'll go.",
        [],
        errand_to="npc_kade_east",
        errand_message="The stranger made fire from a nail and a flint.",
    )
    for _ in range(120):
        advance(state, 1000)
        if any(p["kind"] == "told" for p in state.get("pending_minds", [])):
            break
    pending = next(p for p in state["pending_minds"] if p["kind"] == "told")
    assert pending["npc_id"] == "npc_kade_east" and pending["why"] == "npc_jory_venn" and "fire" in pending["message"]
    kade, jory = npc(state, "npc_kade_east"), npc(state, "npc_jory_venn")
    options = village.hearing_options(state, kade, jory)
    assert {"carry_on", "come_see", "go_with"} <= set(options)
    record = village.apply_hearing(
        state,
        kade,
        jory,
        pending["message"],
        {
            "teller_line": "Kade! You'll want to see this.",
            "listener_line": "Fire? Show me.",
            "move": "come_see",
            "pass_on_message": "",
            "remember": "",
        },
        0,
        state["journal"],
    )
    assert record["move"] == "come_see" and kade["mind"]["job"]["kind"] == "approach"
    assert kade["mind"]["said"]["text"] == "Fire? Show me." and jory["mind"]["said"]["text"].startswith("Kade!")


def test_a_move_the_listener_was_not_offered_is_just_carrying_on():
    import village

    state = unit_state()
    kade, jory = npc(state, "npc_kade_east"), npc(state, "npc_jory_venn")
    record = village.apply_hearing(
        state,
        kade,
        jory,
        "news",
        {"teller_line": "a", "listener_line": "b", "move": "admit", "pass_on_message": "", "remember": ""},
        0,
        state["journal"],
    )
    assert record["move"] == "carry_on" and not (kade.get("mind") or {}).get("job")
