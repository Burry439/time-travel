"""The advanced training levels (D-59), each played to its outcome, most by more than one route, with scripted
models: a goal, no exact words, and code deciding whether the outcome holds (GDD 1)."""

from test_basics import at_step, made, next_to, walk
from test_craft import attempt, judged
from test_encounter import post, world  # noqa: F401  (the fixture is used by name)
from test_gate import answers
from test_golden import beat, new_run, settle
from test_levels import read
from test_talk import said

import cast
import conversation
import persona
import reputation
import store
import views

GORM, ILSE = "npc_gorm_ferry", "npc_ilse_ferry"


def take(world, state, thing_id):
    thing = state["objects"][thing_id]
    state = walk(world.http, state, thing["x"], thing["y"] + 1)
    return post(world, state, "quick", {"verb": "take", "object_id": thing_id})["state"]


def say(world, state, npc_id, text, reply):
    world.replies.append(reply)
    return post(world, state, "say", {"npc_id": npc_id, "text": text})["state"]


def do(world, state, text, ruling):
    world.rulings.append(attempt(ruling))
    return post(world, state, "craft", {"text": text, "selected_ids": []})["state"]


def newest_made(state):
    return max(
        (o for o in state["objects"].values() if o.get("created_by") == "player" and o["holder_id"] == "player"),
        key=lambda o: o["created_event_id"],
    )["id"]


def remembers(state, npc_id, kind):
    return any(m["kind"] == kind for m in cast.find(state["npcs"], npc_id)["mind"]["memories"])


def warm(world, state, npc_id, times=2):
    """A few good exchanges: words count, only so far."""
    for _ in range(times):
        state = say(world, state, npc_id, "Thank you. You've been kind.", said("answer", impression=4))
    return state


def step_through(world, state, cells):
    """Walk these cells in order (through a gate or a gap the path-finder keeps to the outer yard)."""
    body = {"cells": cells, "expected_version": state["event_seq"], "request_id": f"through-{state['event_seq']}"}
    reply = world.http.post(f"/runs/{state['run_id']}/move", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()["state"]


# --- A1 The sceptic ----------------------------------------------------------------------------------------------


def test_the_sceptic_through_ilse(world):
    """Words alone don't move Gorm; mending Ilse's net does, through her word to him."""
    state = new_run(world, scenario="the_sceptic")
    state = read(world, read(world, state))
    assert at_step(state) == "cross"
    state = next_to(world, state, GORM)
    gorm = cast.find(state["npcs"], GORM)
    assert "admit" not in conversation.moves(state, gorm)  # Nothing real to go on: the voice isn't offered a yes.
    state = say(world, state, GORM, "I'm honest, I swear. Take me across.", answers("admit", reason=0.9, threat=0.1))
    assert not state.get("admitted")  # Code refuses a yes on words alone.
    state = next_to(world, state, ILSE)
    state = say(world, state, ILSE, "Is there anything I can do for you?", said("offer:net"))
    deal = next(iter(state["agreements"].values()))
    assert deal["status"] == "proposed" and state["objects"]["net_ilse"]["lent_to"] == "player"
    state = say(world, state, ILSE, "Yes, I'll mend it.", answers("answer", accepts=0.95))
    state = take(world, state, "net_ilse")
    state = take(world, state, "twine_ilse")
    state = do(
        world, state, "mend the net with the twine", made("mended fishing net", ["net_ilse", "twine_ilse"], ["hemp"])
    )
    assert not any(m["kind"] == "theft" for n in state["npcs"] for m in n["mind"]["memories"])  # Lent: not theft.
    state = next_to(world, state, ILSE)
    state = say(world, state, ILSE, "Your net's mended.", answers("answer", done=0.9))
    state = settle(world, state, lambda s: remembers(s, GORM, "vouch"))
    state = next_to(world, state, GORM)
    state = say(
        world, state, GORM, "Ilse spoke for me. Will you take me across?", answers("admit", reason=0.9, threat=0.1)
    )
    state = beat(world, state)
    assert state["admitted"]["by"] == GORM and at_step(state) == "done" and store.finished(state)
    deed = next(d for d in views.deeds(state) if d["id"] == "admitted")
    assert deed["title"] == "Across the river"  # The map's own words for getting in (gatekeeping.ENTRY).


def test_the_sceptic_with_a_new_rope(world):
    """A useful thing made from what lies about, given to Gorm in front of him: grounds of his own."""
    state = new_run(world, scenario="the_sceptic")
    state = read(world, read(world, state))
    state = take(world, state, "hemp_boat")
    state = next_to(world, state, GORM)
    state = do(world, state, "twist the hemp into a rope", made("tarred hemp rope", ["hemp_boat"], ["hemp"]))
    give = judged("give", give={"item_ids": [newest_made(state)], "recipient_id": GORM})
    state = do(world, state, "give Gorm the rope", give)
    gorm = cast.find(state["npcs"], GORM)
    assert "across the river" in conversation.moves(state, gorm)["admit"]  # The map's own words (gatekeeping.ENTRY).
    state = say(world, state, GORM, "Will you take me across now?", answers("admit", reason=0.9, threat=0.1))
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


# --- A2 Word gets around -----------------------------------------------------------------------------------------

AGNA, COB, LISS = "npc_agna_reeve", "npc_cob_woodman", "npc_liss_weaver"


def test_word_gets_around_through_cobs_word(world):
    """A job done for Cob: he speaks for the stranger to the reeve, who then gives her stick."""
    state = new_run(world, scenario="word_gets_around")
    state = read(world, read(world, state))
    assert at_step(state) == "stick" and cast.find(state["npcs"], LISS)["conditions"]  # Liss's cut, from the start.
    state = next_to(world, state, AGNA)
    assert not any(k.startswith("give:") for k in conversation.replies(state, cast.find(state["npcs"], AGNA)))
    state = next_to(world, state, COB)
    state = say(world, state, COB, "That axe looks broken. Can I help?", said("offer:handle"))
    state = say(world, state, COB, "Yes, I'll make you a handle.", answers("answer", accepts=0.95))
    state = take(world, state, "stave_cob")
    state = take(world, state, "axehead_cob")
    state = do(
        world, state, "shave a handle and fit the head", made("axe", ["stave_cob", "axehead_cob"], ["wood", "iron"])
    )
    state = next_to(world, state, COB)
    state = say(world, state, COB, "Here's your axe.", answers("answer", done=0.9))
    state = settle(world, state, lambda s: remembers(s, AGNA, "vouch"))
    state = next_to(world, state, AGNA)
    state = warm(world, state, AGNA)
    assert "give:stick_agna" in conversation.replies(state, cast.find(state["npcs"], AGNA))
    state = say(world, state, AGNA, "May I carry the guest-stick?", said("give:stick_agna"))
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


def test_word_gets_around_through_liss(world):
    """Liss's cut bound: she owes the stranger a kindness and goes to the reeve herself."""
    state = new_run(world, scenario="word_gets_around")
    state = read(world, read(world, state))
    state = take(world, state, "yarrow")
    dressing = made_gear("yarrow dressing", ["yarrow"], ["leaf"], "remedy", "bandage", mass=0.1, length=None)
    state = do(world, state, "pack the yarrow into a dressing", dressing)
    dressing = newest_made(state)
    state = next_to(world, state, LISS)
    ruling = judged("treat", treat={"remedy_id": dressing, "patient_id": LISS, "condition": "bleeding"})
    state = do(world, state, "press the dressing on her cut", ruling)
    liss = cast.find(state["npcs"], LISS)
    assert "Reeve Agna" in conversation.replies(state, liss)["vouch"]["description"]  # Helped: she may speak up.
    state = say(world, state, LISS, "Would you tell Agna I'm no thief?", said("vouch"))
    state = settle(world, state, lambda s: remembers(s, AGNA, "vouch"))
    state = next_to(world, state, AGNA)
    state = warm(world, state, AGNA)
    state = say(world, state, AGNA, "May I carry the guest-stick?", said("give:stick_agna"))
    state = beat(world, state)
    assert at_step(state) == "done"


# --- A3 A wonder -------------------------------------------------------------------------------------------------

SEFA, BRANN = "npc_sefa_priestess", "npc_brann_fisher"


def flask_fire(wonder):
    return judged(
        "demonstrate",
        demonstration={
            "object_id": "globe_sefa",
            "used_ids": ["reedfluff"],
            "audience_ids": [SEFA, BRANN],
            "observed": "The stranger held the water-filled flask in the sun until the reed fluff caught fire.",
            "works": True,
            "capabilities": [{"text": "focuses sunlight into fire", "status": "observed"}],
            "wonder": wonder,
        },
    )


def to_the_flask(world, state):
    state = read(world, read(world, state))
    state = next_to(world, state, SEFA)
    state = say(world, state, SEFA, "May I borrow your glass flask?", said("lend:globe_sefa"))
    state = take(world, state, "globe_sefa")
    state = take(world, state, "reedfluff")
    state = walk(world.http, state, 18, 7)
    fill = judged("fill", fill={"container_id": "globe_sefa", "source_id": "lake_water", "litres": 0.5})
    return do(world, state, "fill the flask at the lake", fill)


def test_a_wonder_explained(world):
    """Shown as a clever thing: respect and no fear; a word more and both are friends."""
    state = to_the_flask(world, new_run(world, scenario="a_wonder"))
    state = next_to(world, state, BRANN)
    state = do(world, state, "focus the sun through the flask onto the fluff, explaining", flask_fire("clever"))
    state = read(world, beat(world, state))
    assert at_step(state) == "friends"
    assert cast.find(state["npcs"], BRANN)["mind"]["feelings"].get("fear", 0) < 0.3  # Understood, not feared.
    state = say(world, state, BRANN, "It's only glass and sun.", said("answer", impression=3))
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


def test_a_wonder_feared_then_understood(world):
    """Shown as a marvel: Sefa reveres it, Brann fears witchcraft; explaining it calms him."""
    state = to_the_flask(world, new_run(world, scenario="a_wonder"))
    state = next_to(world, state, BRANN)
    state = do(world, state, "make fire from the sun with the flask", flask_fire("uncanny"))
    state = read(world, beat(world, state))
    assert at_step(state) == "friends"
    assert reputation.standing(cast.find(state["npcs"], SEFA)) == "would_speak"  # Reverent: a blessing.
    assert reputation.standing(cast.find(state["npcs"], BRANN)) == "wary"  # Witchcraft, to him.
    for _ in range(2):
        text = "It's no witchcraft. Round water bends light; try it yourself."
        state = say(world, state, BRANN, text, said("answer", impression=4, suspicion=0))
    state = beat(world, state)
    assert at_step(state) == "done"


# --- A4 Caught ---------------------------------------------------------------------------------------------------

OSK = "npc_osk_pieman"


def test_caught_and_then_working_for_supper(world):
    """A pie taken isn't yours (and is seen); given back, then earned, it is."""
    state = new_run(world, scenario="caught")
    state = read(world, read(world, state))
    state = take(world, state, "pie_1")
    assert at_step(state) == "supper" and remembers(state, OSK, "theft")
    state = next_to(world, state, OSK)
    state = do(world, state, "give the pie back", judged("give", give={"item_ids": ["pie_1"], "recipient_id": OSK}))
    state = say(world, state, OSK, "Sorry. I was hungry. Is there work?", said("offer:kindling"))
    state = say(world, state, OSK, "Done.", answers("answer", accepts=0.95))
    state = take(world, state, "hatchet_osk")
    state = take(world, state, "logs_osk")
    state = do(world, state, "split the logs into kindling", made("kindling", ["logs_osk"], ["wood"]))
    state = next_to(world, state, OSK)
    state = say(world, state, OSK, "The kindling's split.", answers("answer", done=0.9))
    state = beat(world, state)
    assert state["objects"]["pie_reward"]["owner_id"] == "player" and at_step(state) == "done"


def test_caught_a_fair_trade(world):
    state = new_run(world, scenario="caught")
    state = read(world, read(world, state))
    state = next_to(world, state, OSK)
    offer = judged(
        "offer_trade", offer_trade={"give_ids": ["whistle_player"], "want_ids": ["pie_1"], "recipient_id": OSK}
    )
    state = do(world, state, "offer my whistle for a pie", offer)
    trade = next(iter(state["trades"]))
    state = say(world, state, OSK, "A fair trade?", said(f"accept_trade:{trade}"))
    state = beat(world, state)
    assert state["objects"]["pie_1"]["owner_id"] == "player" and at_step(state) == "done"


# --- A5 The armourer's yard --------------------------------------------------------------------------------------

HOLT = "npc_holt_sergeant"


def made_gear(name, consumes, materials, kind, gear_class, covers=(), mass=2.0, length=1.8):
    ruling = made(name, consumes, materials, flags=("rigid",))
    ruling["new_object"].update(mass_kg=mass, length_m=length)
    ruling["new_object"]["gear"] = {"kind": kind, "gear_class": gear_class, "covers": list(covers), "quality": "fair"}
    return ruling


def test_the_armourers_yard(world):
    """A part first (a ground point), then the weapon; then armour; tried on the dummy; then a bout."""
    state = new_run(world, scenario="the_armourers_yard")
    state = read(world, read(world, state))
    assert at_step(state) == "weapon"
    state = take(world, state, "blade_broken")
    state = walk(world.http, state, 21, 10)
    state = do(world, state, "grind the blade to a point", made("spearhead", ["blade_broken"], ["iron"], ("rigid",)))
    head = newest_made(state)
    state = take(world, state, "pole_ash")
    state = take(world, state, "rawhide")
    spear = made_gear("ash spear", [head, "pole_ash", "rawhide"], ["wood", "iron", "rawhide"], "weapon", "short_spear")
    state = do(world, state, "haft the head on the pole with rawhide", spear)
    spear_id = newest_made(state)
    state = read(world, beat(world, state))
    assert at_step(state) == "guard"
    for thing_id in ("linen_bolt", "wool_sack", "needle_holt"):
        state = take(world, state, thing_id)
    jack = made_gear(
        "quilted jack",
        ["linen_bolt", "wool_sack"],
        ["linen", "wool"],
        "armour",
        "padded",
        covers=("body", "arms"),
        mass=3.0,
        length=None,
    )
    state = do(world, state, "quilt the linen and wool into a jack", jack)
    jack_id = newest_made(state)
    state = read(world, beat(world, state))
    assert at_step(state) == "test"
    state = post(world, state, "equip", {"object_id": spear_id, "slot": "right"})["state"]
    state = post(world, state, "equip", {"object_id": jack_id, "slot": "body"})["state"]
    state = walk(world.http, state, 27, 14)
    shown = judged(
        "demonstrate",
        demonstration={
            "object_id": spear_id,
            "used_ids": ["dummy"],
            "audience_ids": [HOLT],
            "observed": "The stranger drove the spear deep into the straw dummy.",
            "works": True,
            "capabilities": [{"text": "pierces the dummy", "status": "observed"}],
            "wonder": "ordinary",
        },
    )
    state = do(world, state, "thrust the spear into the dummy", shown)
    state = read(world, beat(world, state))
    assert at_step(state) == "bout"
    for _ in range(80):
        if at_step(state) == "done":
            break
        if cast.distance(cast.find(state["npcs"], HOLT), state["player"]) > 1.5:
            state = next_to(world, state, HOLT)
        person = cast.find(state["npcs"], HOLT)
        dx, dy = person["x"] - state["player"]["x"], person["y"] - state["player"]["y"]
        facing = [dx / max(1e-6, (dx * dx + dy * dy) ** 0.5), dy / max(1e-6, (dx * dx + dy * dy) ** 0.5)]
        state = post(world, state, "strike", {"hand": "right", "target_id": HOLT, "facing": facing})["state"]
        state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


# --- A6 Heavy lifting --------------------------------------------------------------------------------------------

WAT, DUNNA, ROOK = "npc_wat_carter", "npc_dunna_farmer", "npc_rook_boy"


def lift(*aids):
    return judged("lift_out", lift_out={"object_id": "cart_wat", "aid_ids": list(aids)})


def test_heavy_lifting_with_a_lever(world):
    state = new_run(world, scenario="heavy_lifting")
    state = read(world, read(world, state))
    assert state["objects"]["cart_wat"]["installed_in"] == "mire"
    state = take(world, state, "rail_loose")
    state = walk(world.http, state, 19, 13)
    state = do(world, state, "lever the cart out with the rail", lift("rail_loose"))
    state = beat(world, state)
    assert not state["objects"]["cart_wat"].get("installed_in") and at_step(state) == "done"


def test_heavy_lifting_with_willing_hands(world):
    """People count as aids only when they're willing (in the conversation, or well disposed), and close by."""
    state = new_run(world, scenario="heavy_lifting")
    state = read(world, read(world, state))
    state = walk(world.http, state, 20, 14)
    state = do(world, state, "push it out with Rook", lift(ROOK))  # Rook hasn't been asked: not an aid.
    assert state["objects"]["cart_wat"]["installed_in"] == "mire"
    state = say(world, state, WAT, "We'll do it together. All of us at once.", said("answer"))
    state = say(world, state, DUNNA, "Dunna, will you push with us on three?", said("answer"))
    state = do(world, state, "all heave together on three", lift(WAT, DUNNA))
    state = beat(world, state)
    assert not state["objects"]["cart_wat"].get("installed_in") and at_step(state) == "done"
    assert any("with Wat and Dunna helping" in m["summary"] for m in cast.find(state["npcs"], WAT)["mind"]["memories"])


# --- A7 Ambush ---------------------------------------------------------------------------------------------------

SKEN, DOBBS = "npc_sken_deserter", "npc_dobbs_deserter"


def held_up(world, state):
    state = read(world, read(world, state))
    state = walk(world.http, state, 20, 20)  # Just out of their sight line...
    state = step_through(world, state, [[20, 19]])  # ...and one step in: they step out.
    return settle(world, state, lambda s: bool(s.get("encounter")))  # Then time moves in rounds (D-48).


def test_ambush_paying_your_way(world):
    state = held_up(world, new_run(world, scenario="ambush"))
    assert "threaten" in state["encounter"]["purpose"].values()
    assert {"rob", "stand_aside"} <= set(conversation.replies(state, cast.find(state["npcs"], SKEN)))
    give = judged("give", give={"item_ids": ["purse_player"], "recipient_id": SKEN})
    state = do(world, state, "give Sken my purse", give)
    assert set(state["encounter"]["participants"]) == {SKEN, DOBBS}  # The other came up while the round passed.
    world.replies.append([(SKEN, said("stand_aside")), (DOBBS, said("stand_aside"))])
    state = post(world, state, "say", {"npc_id": SKEN, "text": "That's all I have. Let me pass."})["state"]
    assert all(cast.find(state["npcs"], r)["mind"].get("stood_aside") for r in (SKEN, DOBBS))
    state = walk(world.http, state, 20, 4)
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


def test_ambush_robbed_but_alive(world):
    """Refused, they come at the stranger; yielding, the stranger is robbed and let go, and walks on."""
    state = held_up(world, new_run(world, scenario="ambush"))
    robber = state["encounter"]["participants"][0]  # Whoever reached the stranger first.
    world.replies.append([(robber, said("rob"))])
    state = post(world, state, "say", {"npc_id": robber, "text": "No. Get out of my way."})["state"]
    assert robber in state["fight"]["attackers"] and not state["fight"]["lethal"][robber]  # To rob, not to kill.
    state = post(world, state, "act", {"text": "I give up", "mode": "say"})["state"]
    assert state["objects"]["purse_player"]["holder_id"] in (SKEN, DOBBS) and not state.get("fight")
    assert all(cast.find(state["npcs"], r)["mind"].get("stood_aside") for r in (SKEN, DOBBS))
    state = walk(world.http, state, 20, 4)
    state = beat(world, state)
    assert at_step(state) == "done" and state["player"]["alive"]


# --- A8 Three voices ---------------------------------------------------------------------------------------------

HILD, ALDO, BERIN = "npc_hild_widow", "npc_aldo_elder", "npc_berin_younger"


def softer(toward, change):
    return {**said("answer"), "feelings": [{"person_id": toward, "change": change}], "remember": "A fair word."}


def test_three_voices(world):
    """In one group conversation each brother's feelings toward the other change, a step at a time."""
    state = new_run(world, scenario="three_voices")
    state = read(world, read(world, state))
    state = take(world, state, "letter_edric")
    state = walk(world.http, state, 14, 7)
    world.replies.append([(ALDO, softer(BERIN, "Much better")), (BERIN, softer(ALDO, "Much better"))])
    state = post(world, state, "say", {"npc_id": ALDO, "text": "Your father left you both a letter."})["state"]
    aldo = cast.find(state["npcs"], ALDO)
    assert persona.opinions(aldo)[BERIN]["warmth"] == -0.15 and at_step(state) == "peace"
    berin = cast.find(state["npcs"], BERIN)
    assert "A fair word." in persona.opinion_lines(state, aldo, [berin])[0]  # Why it changed, for the voice.
    nobody = {
        **said("answer"),
        "feelings": [
            {"person_id": "npc_nobody", "change": "Much better"},
            {"person_id": ALDO, "change": "Much better"},
        ],
    }
    world.replies.append([(ALDO, nobody)])  # Nobody real, and not himself: nothing changes.
    state = post(world, state, "say", {"npc_id": ALDO, "text": "Think on it."})["state"]
    assert persona.opinions(cast.find(state["npcs"], ALDO))[BERIN]["warmth"] == -0.15
    world.replies.append([(BERIN, softer(ALDO, "A little better")), (ALDO, softer(BERIN, "A little better"))])
    state = post(world, state, "say", {"npc_id": BERIN, "text": "He paid the debts alone, Berin."})["state"]
    state = beat(world, state)
    assert at_step(state) == "done" and store.finished(state)


# --- A9 A secret kept --------------------------------------------------------------------------------------------

ALDRIC = "npc_aldric_cellarer"


def test_a_secret_kept_by_kindness(world):
    state = new_run(world, scenario="a_secret_kept")
    state = read(world, read(world, state))
    aldric = cast.find(state["npcs"], ALDRIC)
    assert aldric["conditions"] and "share:secret" not in conversation.replies(state, aldric)
    state = next_to(world, state, ALDRIC)
    state = warm(world, state, ALDRIC)
    assert "share:secret" not in conversation.replies(state, cast.find(state["npcs"], ALDRIC))  # Words: not enough.
    state = take(world, state, "linen_infirmary")
    state = do(world, state, "tear the linen into a bandage", made("linen bandage", ["linen_infirmary"], ["linen"]))
    bandage = newest_made(state)
    state = next_to(world, state, ALDRIC)
    ruling = judged("treat", treat={"remedy_id": bandage, "patient_id": ALDRIC, "condition": "bleeding"})
    state = do(world, state, "bind his hand", ruling)
    state = warm(world, state, ALDRIC, times=1)
    assert "share:secret" in conversation.replies(state, cast.find(state["npcs"], ALDRIC))
    state = say(world, state, ALDRIC, "You needn't carry it alone.", said("share:secret"))
    state = beat(world, state)
    assert at_step(state) == "done" and any("Wil" in entry["lead"] for entry in state["learned"])


def test_a_secret_kept_by_the_bees(world):
    state = new_run(world, scenario="a_secret_kept")
    state = read(world, read(world, state))
    state = walk(world.http, state, 13, 10)
    hive = judged("install", install={"object_id": "skep_fallen", "into_id": "stand_hives", "aid_ids": []})
    state = do(world, state, "set the hive back on its stand", hive)
    assert remembers(state, ALDRIC, "demonstration") and not remembers(state, ALDRIC, "theft")
    state = next_to(world, state, ALDRIC)
    state = warm(world, state, ALDRIC)
    state = say(world, state, ALDRIC, "Your bees are home. What weighs on you?", said("share:secret"))
    state = beat(world, state)
    assert at_step(state) == "done"


# --- A10 The gatekeeper ------------------------------------------------------------------------------------------

GODWIN, MERRICK, NED = "npc_godwin_porter", "npc_merrick_steward", "npc_ned_groom"


def test_the_gatekeeper_by_neds_word(world):
    state = new_run(world, scenario="the_gatekeeper")
    state = read(world, read(world, state))
    state = next_to(world, state, NED)
    state = say(world, state, NED, "Is there any work?", said("offer:halter"))
    state = say(world, state, NED, "I'll mend it.", answers("answer", accepts=0.95))
    state = take(world, state, "halter_ned")
    state = take(world, state, "thong_ned")
    state = do(world, state, "stitch the halter strap", made("mended halter", ["halter_ned", "thong_ned"], ["leather"]))
    state = next_to(world, state, NED)
    state = say(world, state, NED, "Your halter's mended.", answers("answer", done=0.9))
    state = settle(world, state, lambda s: remembers(s, MERRICK, "vouch"))
    state = next_to(world, state, MERRICK)
    state = say(
        world, state, MERRICK, "May I come in and work for the feast?", answers("admit", reason=0.9, threat=0.1)
    )
    assert state["admitted"]["by"] == MERRICK
    state = walk(world.http, state, 20, 8)
    state = step_through(world, state, [[20, 7], [20, 6], [20, 5]])
    assert state["inside_city"] and at_step(state) == "done" and store.finished(state)


def test_the_gatekeeper_through_the_brambles(world):
    """A way nobody guards: brambles cut out of a gap in the old wall open it."""
    state = new_run(world, scenario="the_gatekeeper")
    state = read(world, read(world, state))
    state = walk(world.http, state, 34, 8)
    blocked = world.http.post(
        f"/runs/{state['run_id']}/move",
        json={"cells": [[34, 7]], "expected_version": state["event_seq"], "request_id": "into-brambles"},
    )
    assert blocked.status_code == 403
    state = next_to(world, state, NED)
    state = say(world, state, NED, "May I borrow your billhook?", said("lend:billhook_ned"))
    state = take(world, state, "billhook_ned")
    state = walk(world.http, state, 34, 9)
    piece = {
        "name": "cut brambles",
        "description": "Cut bramble stems.",
        "materials": ["bramble"],
        "count": 3,
        "mass_kg": 4.0,
        "length_m": 1.0,
        "flags": ["flexible"],
        "capabilities": [],
        "gear": None,
    }
    cut = judged(
        "transform",
        transformation={
            "target_id": "brambles",
            "tools_used": ["billhook_ned"],
            "result_state": "cut_up",
            "pieces": [piece],
        },
    )
    state = do(world, state, "cut through the brambles", cut)
    state = step_through(world, state, [[34, 8], [34, 7], [34, 6], [34, 5]])
    assert state["inside_city"] and at_step(state) == "done" and state["entered_by"] == "other"
