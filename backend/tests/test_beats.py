"""Story beats (D-59): what a level's story has someone say is said in their own words, in the reply that brings the
moment about; an authored line says only what that reply left out. Found by the user's first play of "A
cup of water": asked how she was, Wenna said "fine", and then a scripted line asked for water."""

import pytest
from test_advanced import GORM, newest_made, take
from test_basics import WENNA, at_step, made, next_to, ui, walk
from test_craft import attempt, judged
from test_encounter import post, world  # noqa: F401  (the fixture is used by name)
from test_gate import answers
from test_golden import beat, new_run
from test_levels import read
from test_talk import said

import app as service
import beats
import cast
import content
import rules
import scenario
import store

AUTHORED_ASK = "Water, that's what's wrong."
HER_OWN_ASK = (
    "Parched, dear, that's how I am: water's what's wrong. My leg won't take me to the well and the boy's off after "
    "the hens. My cup's by the well. Would you fill it for me?"
)


@pytest.fixture
def shown(world, monkeypatch):
    """What the voice was given, each round (on top of the world's scripted scenes)."""
    contexts = []
    scripted = service.voice.scene

    def watch(context, fallback, allowed=True):
        contexts.append(context)
        return scripted(context, fallback, allowed)

    monkeypatch.setattr(service.voice, "scene", watch)
    return contexts


def beat_for(context, npc_id):
    return next((p.get("story_beat") for p in context["people"] if p["id"] == npc_id), None)


def their_lines(state, npc_id):
    return [t["text"] for t in cast.find(state["npcs"], npc_id)["mind"]["talk"] if t["who"] == "them"]


def voiced(reply, text):
    """A scripted reply, in these words, that says it got the speaker's story beat across."""
    return {**reply, "story_beat": True, "text": text}


def at_talk(world):
    state = new_run(world, scenario="cup_of_water")
    state = read(world, read(world, state))  # The welcome, then walking's cards.
    state = beat(world, next_to(world, state, WENNA))
    assert at_step(state) == "talk"
    return read(world, state)


def ask_wenna(world, reply):
    state = at_talk(world)
    world.replies.append(reply)
    state = post(world, state, "say", {"npc_id": WENNA, "text": "Good morning. How are you?"})["state"]
    state = beat(world, state)
    assert at_step(state) == "look"
    return state, next(c for c in state["learned"] if c.get("asks"))


def test_asked_how_she_is_wenna_answers_with_her_thirst(world, shown):
    state, asked = ask_wenna(world, voiced(said("answer"), HER_OWN_ASK))
    given = beat_for(shown[-1], WENNA)
    assert AUTHORED_ASK in given["get_across"] and "only_if" not in given  # Due in this very reply.
    assert their_lines(state, WENNA) == [HER_OWN_ASK]  # One reply, hers: nothing scripted after it.
    assert asked["said"] == HER_OWN_ASK  # The journal quotes what she really said.


def test_what_her_reply_left_out_is_all_that_follows_it(world, shown):
    short = "Water, that's what's wrong. My leg won't take me to the well today. My cup's by the well."
    state, asked = ask_wenna(world, voiced(said("answer"), short))  # Says she told it all; she didn't.
    assert their_lines(state, WENNA) == [short, "Fill it for me, would you?"]  # Only the rest, as its follow-on.
    *_, reply, rest = state["encounter"]["log"]  # In the conversation, right after her reply, in its round.
    assert rest == {
        "round": reply["round"],
        "who": WENNA,
        "kind": "reply",
        "text": "Wenna: “Fill it for me, would you?”",
    }
    assert asked["said"] == "My cup's by the well. Fill it for me, would you?"  # Her own words didn't carry it all.


def test_a_reply_that_keeps_it_back_is_never_spoken_over(world, shown):
    """She answers a greeting and keeps her thirst to herself: no scripted ask follows, and the story waits until
    she says it, offered again the next time she speaks."""
    state = at_talk(world)
    world.replies.append({**said("answer"), "text": "Good morning to you, dear."})
    state = beat(world, post(world, state, "say", {"npc_id": WENNA, "text": "Good morning!"})["state"])
    assert at_step(state) == "talk" and their_lines(state, WENNA) == ["Good morning to you, dear."]
    assert not any(c.get("asks") for c in state.get("learned", []))  # Nothing asked of you she didn't ask.
    world.replies.append(voiced(said("answer"), HER_OWN_ASK))
    state = post(world, state, "say", {"npc_id": WENNA, "text": "Are you all right?"})["state"]
    assert AUTHORED_ASK in beat_for(shown[-1], WENNA)["get_across"]  # Still on her mind.
    state = beat(world, state)
    assert at_step(state) == "look" and their_lines(state, WENNA)[-1] == HER_OWN_ASK


def test_her_thanks_wait_for_the_water_and_come_with_it(world, shown):
    state = at_talk(world)
    world.replies.append(voiced(said("answer"), HER_OWN_ASK))
    state = post(world, state, "say", {"npc_id": WENNA, "text": "Hello there."})["state"]
    state = read(world, beat(world, state))
    state = ui(world, state, "inspect")
    state = read(world, state)
    cup = state["objects"]["cup_wenna"]
    state = walk(world.http, state, cup["x"], cup["y"] + 1)
    state = read(world, post(world, state, "quick", {"verb": "take", "object_id": "cup_wenna"})["state"])
    state = read(world, ui(world, state, "pack"))
    world.rulings.append(
        attempt(judged("fill", fill={"container_id": "cup_wenna", "source_id": "bucket_well", "litres": 0.3}))
    )
    state = post(world, state, "craft", {"text": "fill the cup from the well bucket", "selected_ids": []})["state"]
    state = read(world, beat(world, state))
    assert at_step(state) == "give"
    state = next_to(world, state, WENNA)
    world.replies.append(said("answer"))
    state = post(world, state, "say", {"npc_id": WENNA, "text": "Your water's coming."})["state"]
    assert beat_for(shown[-1], WENNA) is None  # Not given yet: her thanks (and the mill) wait.
    world.rulings.append(attempt(judged("give", give={"item_ids": ["cup_wenna"], "recipient_id": WENNA})))
    thanks = (
        "Oh, bless you, child. Ada from the mill's by the coop for her eggs; she's always short of strong hands. "
        "Pip, run and tell her what this one did for me!"
    )
    world.replies.append(voiced(said("answer"), thanks))
    body = {"kind": "do", "text": "give the cup of water to Wenna", "target_id": WENNA, "selected_ids": ["cup_wenna"]}
    state = post(world, state, "encounter/act", body)["state"]
    assert "Ada from the mill" in beat_for(shown[-1], WENNA)["get_across"]  # Handed over in this round: due now.
    state = beat(world, state)
    assert at_step(state) == "journal" and their_lines(state, WENNA)[-1] == thanks  # Nothing scripted after.
    mill = next(c for c in state["learned"] if "mill" in c["lead"])
    assert mill["said"] == thanks


def test_a_yes_that_is_his_to_give_comes_only_if_he_gives_it(world, shown):
    """Gorm's "get aboard" is offered only_if he lets the stranger across. Since D-62 a yes is open to him from the
    start (he weighs it himself), so the beat is on offer; he keeps it back while he has no reason, and a yes his own
    reading doesn't support is never his answer."""
    state = new_run(world, scenario="the_sceptic")
    state = read(world, read(world, state))
    state = next_to(world, state, GORM)
    say = {"npc_id": GORM, "text": "I'm honest, I swear. Take me across."}
    world.replies.append(voiced(answers("answer", reason=0.1, threat=0.1), "I need a reason to trust you first."))
    state = post(world, state, "say", say)["state"]
    assert beat_for(shown[-1], GORM) is not None  # His to weigh (D-62): offered, only_if he lets them across.
    assert not state.get("admitted") and beats.answered(cast.find(state["npcs"], GORM), "cross") is None
    state = take(world, state, "hemp_boat")
    state = next_to(world, state, GORM)
    world.rulings.append(attempt(made("tarred hemp rope", ["hemp_boat"], ["hemp"])))
    state = post(world, state, "craft", {"text": "twist the hemp into a rope", "selected_ids": []})["state"]
    world.rulings.append(attempt(judged("give", give={"item_ids": [newest_made(state)], "recipient_id": GORM})))
    state = post(world, state, "craft", {"text": "give Gorm the rope", "selected_ids": []})["state"]
    aboard = "A rope like that earns a crossing. Get aboard, then, and keep your hands where I can see them."
    world.replies.append(voiced(answers("admit", reason=0.9, threat=0.1), aboard))
    state = post(world, state, "say", {"npc_id": GORM, "text": "Will you take me across now?"})["state"]
    assert "you let the stranger through" in beat_for(shown[-1], GORM)["only_if"]  # His to give now: due, if he does.
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)
    assert their_lines(state, GORM)[-1] == aboard  # His own yes, and nothing scripted after it.


def test_the_next_steps_opening_words_come_in_the_same_reply(monkeypatch):
    """A step's end and the next step's opening lines are one moment: a person who says both says them in one
    reply (Kade, after a bout the stranger gave up in words), and neither is said again after it."""
    kade = {"id": "npc_kade_east", "name": "Kade", "mind": {"memories": [], "feelings": {}}}
    level = {
        "id": "beats_probe",
        "version": 1,
        "steps": [
            {"id": "bout", "check": {"kind": "talked_to", "npc": kade["id"]}, "on_done": [said_by(kade, "Not bad.")]},
            {"id": "why", "check": {"kind": "always"}, "on_start": [said_by(kade, "So why are you here?")]},
        ],
    }
    monkeypatch.setitem(content.LEVELS, "beats_probe", level)
    state = {"scenario": "beats_probe", "npcs": [kade], "player": {}, "sim_time_ms": 0, "journal": []}
    state["tutorial"] = {"step": 0, "read": 0, "version": 1, "fired": [], "started_at": 0}
    beat = beats.due(state, kade["id"], "I give up!", None, 0)[kade["id"]]
    assert beat == {"keys": ["bout", "why:start"], "get_across": "Not bad. So why are you here?"}
    kade["mind"]["talk"] = [{"who": "stranger", "text": "I give up!", "at": 0}]
    assert beats.came(state, beat)
    beats.mark_answered(kade, beat, "Enough! Not bad at all. So, why are you here?")
    assert beats.due(state, kade["id"], "Well?", None, 0) == {}  # Answered: not offered twice.
    scenario.run(state, level["steps"][1]["on_start"], 0, "why:start")
    assert not state["journal"] and kade["mind"]["talk"][-1]["who"] == "stranger"  # Not said again as written.


def said_by(npc, text):
    return {"kind": "npc_says", "npc": npc["id"], "text": text}


def lines_in(effects):
    return [spec for spec in effects if spec["kind"] == "npc_says"]


def test_what_people_say_in_a_story_follows_what_happens():
    """Rules for every level's authored words, so a story reads as people answering what happened."""
    screen_only = ("ui", "asked_device", "always")  # Pressing J, opening the pack: nothing anyone in the world sees.
    for level in content.LEVELS.values():
        for step in level.get("steps", []):
            where = (level["id"], step["id"])
            moments = [step.get("on_done", []), step.get("on_start", [])] + [t["do"] for t in step.get("triggers", [])]
            for effects in moments:
                for spec in lines_in(effects):
                    assert spec["npc"] in content.CARDS and isinstance(spec["text"], str) and spec["text"].strip(), (
                        where
                    )
                speakers = {spec["npc"] for spec in lines_in(effects)}
                for spec in effects:  # What a lead or an offer quotes, someone really says (as a beat, or as written).
                    if (spec["kind"] == "lead" and spec.get("said")) or (spec["kind"] == "offer" and spec.get("says")):
                        assert spec["npc"] in speakers, (*where, spec["kind"], "quotes words nobody says")
            if step["check"]["kind"] in screen_only:  # Nobody reacts to a key the stranger pressed (Corr, on J).
                assert not lines_in(step.get("on_done", [])), (*where, "a line that answers a screen")
            for trigger in step.get("triggers", []):  # Being told something, a person answers in their own words.
                if trigger["when"]["kind"] == "heard_from":
                    listener = trigger["when"]["npc"]
                    assert all(s["npc"] != listener for s in lines_in(trigger["do"])), (*where, trigger["id"])


def test_a_condition_can_be_assumed_for_what_a_reply_could_decide():
    state = {"npcs": [], "player": {}, "tutorial": {}}
    deal = {"kind": "deal", "npc": "npc_x", "status": "fulfilled"}
    assert not rules.holds(state, deal)
    assert rules.holds(state, {"kind": "all", "of": [deal, {"kind": "always"}]}, {"assume": beats._decided})
    assert beats._decision({"kind": "any", "of": [{"kind": "always"}, deal]})[0].startswith("you judge the job")
    assert beats._decision({"kind": "not", "of": deal}) is None


def test_an_authored_line_says_only_what_the_reply_left_out():
    """Real replies from the live runs (D-59), and what of each authored line was still to say after them."""
    odo = "Hm. Good work. Tighter knots next time. Here's one for you: an old soldier at the ruined smithy teaches weapons."
    assert (
        beats.left_to_say(odo, "Hm. Good work. Tighter knots next time.") == odo.split(" Tighter knots next time. ")[1]
    )
    ada = "Full to the brim. Here: your flour. You keep your word; I'll remember it. Mind Corr, the watchman."
    paid = "Good. The trough's full; here's the small sack of flour, as agreed."
    assert beats.left_to_say(ada, paid) == "You keep your word; I'll remember it. Mind Corr, the watchman."
    doran = "Gate's shut to strangers since the fever. Captain lets you in only if someone'll speak for you."
    news = "The city gate's been shut to strangers since the spring fever. The captain lets you in only if someone inside will speak for you."
    assert beats.left_to_say(doran, news) == "" and beats.says_all(news, doran)
    odo_asks = "Help? Hm. Rope, torch, sling, for my round tomorrow. Book's on the table, says how."
    assert beats.left_to_say(odo_asks, "Hm. Rope, torch, sling for my round tomorrow. Book's on the table.") == ""
    ivo = "Oi, you. Pass me my tankard, would you? Knocked it off and my back's gone."
    assert beats.left_to_say(ivo, "I've a trade permit. A hired hand can go in with me.").startswith(
        "Pass me my tankard"
    )
    assert beats.left_to_say(ivo, None) == ivo  # Nothing said in their own words: all of it, as written.
    ask = (
        "Water, that's what's wrong. My leg won't take me to the well. My cup's by the well. Fill it for me, would you?"
    )
    parched = "Hello. I'm parched; my leg won't get me to the well. My cup's by the well: fill it for me, would you?"
    assert beats.left_to_say(ask, parched) == ""  # Told her own way, in order: nothing said again before it.
    no_cup = "Good morning. Water, that's what's wrong. My leg won't take me to the well today."
    assert beats.left_to_say(ask, no_cup) == "My cup's by the well. Fill it for me, would you?"  # "It" needs the cup.
    hal = "Learn? Good. Sword in your right hand, shield in your left. Nobody bleeds in my yard."
    assert beats.left_to_say(hal, "Here to watch, or here to learn? Learn? Good.").startswith("Sword in")


def test_the_next_steps_outcome_can_come_in_the_same_round(monkeypatch):
    """The trough filled in front of Ada, and Ada judging the job done, in one round: her pay comes in that reply,
    only if she judges it done (the next step's line, offered one step ahead)."""
    ada = {"id": "npc_ada_miller", "name": "Ada", "mind": {"memories": [], "feelings": {}}}
    level = {
        "id": "beats_ahead",
        "version": 1,
        "steps": [
            {"id": "work", "check": {"kind": "talked_to", "npc": ada["id"]}},
            {
                "id": "paid",
                "check": {"kind": "deal", "npc": ada["id"], "status": "fulfilled"},
                "on_done": [said_by(ada, "Full to the brim. Here: your flour.")],
            },
        ],
    }
    monkeypatch.setitem(content.LEVELS, "beats_ahead", level)
    state = {"scenario": "beats_ahead", "npcs": [ada], "player": {}, "sim_time_ms": 0, "journal": []}
    state["tutorial"] = {"step": 0, "read": 0, "version": 1, "fired": [], "started_at": 0}
    beat = beats.due(state, ada["id"], "(pours the pail into the trough)", None, 0)[ada["id"]]
    assert beat["keys"] == ["paid"] and beat["only_if"].startswith("you judge the job you asked for done")


def test_a_word_for_the_stranger_is_addressed_to_whoever_decides():
    """Live, Ilse spoke for the stranger to Gorm the ferryman as "Captain" (the city's lines, D-59)."""
    for tone, templates in content.LINES["lines"]["vouch"].items():
        for template in templates:
            assert "Captain" not in template and "Roderic" not in template, (tone, template)


ULF = "npc_ulf_charcoal"
ULF_ASKS = "Fill my pot at the river"


def test_a_story_asks_nothing_of_someone_the_stranger_has_wronged(world, shown):
    """The user's play (2 Oct 2026): they took Ulf's pot without asking and scalded him with it, and Ulf then asked
    them for boiling water and lent them his things. The story proposes, people decide: robbed, Ulf is hostile, so
    nothing it asks of him happens, the step that is his asking waits, and the device says why, once."""
    state = read(world, read(world, new_run(world, scenario="fire_and_water")))
    pot = state["objects"]["pot_ulf"]
    state = walk(world.http, state, pot["x"], pot["y"] + 1)
    state = post(world, state, "quick", {"verb": "take", "object_id": "pot_ulf"})["state"]  # Not lent yet: theft.
    state = next_to(world, state, ULF)
    world.replies.append({**said("demand:pot_ulf"), "text": "That's my pot. Give it back."})
    state = post(world, state, "say", {"npc_id": ULF, "text": "Hello. Can I help?"})["state"]
    assert beat_for(shown[-1], ULF) is None  # Wronged: the story gives him nothing to ask of you.
    for _ in range(3):
        state = beat(world, state)
    assert at_step(state) == "hello"  # His asking is the step: it doesn't come by being spoken to.
    assert not any(ULF_ASKS in line for line in their_lines(state, ULF))
    assert not any(state["objects"][i].get("lent_to") for i in ("flint_ulf", "steel_ulf", "logs_ulf"))
    told = [e["text"] for e in state["device_log"] if "Ulf won't do anything for you" in e["text"]]
    assert len(told) == 1  # Why the story waits, said once (his own feelings decide it, D-63).


def test_what_a_person_does_for_the_stranger_waits_on_their_will():
    """Every favour a story asks (lines, leads, loans, gifts, a word for the stranger) is the person's to do: never
    by someone hostile or down. A step's opening is the world going on, theirs only while they can."""
    state = {"npcs": [], "player": {"x": 0, "y": 0}, "journal": [], "objects": {}, "tutorial": {"fired": []}}
    hal = {"id": "npc_hal_brand", "name": "Hal", "x": 1, "y": 0, "mind": {"memories": [], "feelings": {"anger": 0.9}}}
    state["npcs"].append(hal)
    says = {"kind": "npc_says", "npc": hal["id"], "text": "Here: practice ones."}
    assert not scenario._goes_ahead(state, says, {"moment": "hello"})  # Angry with the stranger: not now.
    assert scenario._goes_ahead(state, says, {"moment": "bout:start"})  # The world going on.
    hal["mind"]["feelings"]["anger"] = 0.0
    assert scenario._goes_ahead(state, says, {"moment": "hello"})
    hal["down"] = True
    assert not scenario._goes_ahead(state, says, {"moment": "bout:start"})
    assert scenario._goes_ahead(state, {"kind": "hurt", "npc": hal["id"], "condition": {}}, {"moment": "x"})
