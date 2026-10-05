"""The village's quests (D-67): many steps, many ways, intertwined. A step is a result in the world, checked by code;
it reaches each person when they know it, with their side of it and what they'd now ask of someone; quest-givers
bring their trouble up themselves when the stranger comes up to them."""

from test_craft import commit, fresh_state, judged
from test_encounter import post, world  # noqa: F401
from test_talk import npc, unit_state

import briefing
import cast
import clock
import conversation
import persona
import stories

HESSA, BREN, DARIN, OREN, JORY, KADE, RODERIC = (
    "npc_hessa_marr",
    "npc_bren_marr",
    "npc_darin_ko",
    "npc_oren_dast",
    "npc_jory_venn",
    "npc_kade_east",
    "npc_roderic_vale",
)


def learn(state, npc_id, **entry):
    """Something this person told the stranger (a lead in their journal)."""
    state.setdefault("learned", []).append({"npc_id": npc_id, "name": npc_id, "lead": "…", **entry})


def test_quest_givers_start_out_with_what_they_would_ask_and_their_side():
    state = unit_state()
    bren = npc(state, BREN)
    assert any("what's eating him" in line for line in persona.needs(bren))
    assert any("Dice and Debts" in line for line in persona.sides(bren))
    context = briefing.converse_context(state, bren, "Hello.", {}, None)
    assert context["what_you_would_ask_of_someone"] and context["your_side_of_things"]
    assert any("would ask of someone" in line for line in persona.sheet_lines(state, bren))  # Their decisions too.
    assert not persona.needs(npc(state, OREN))  # Oren hides it: Bren asks.


def test_a_later_fact_is_theirs_to_tell_only_once_a_step_teaches_it():
    state = unit_state()
    hessa = npc(state, HESSA)
    assert "trough_boards" not in conversation.knowledge(hessa)
    assert "share:trough_boards" not in conversation.replies(state, hessa)
    learn(state, HESSA, fact="sick_guests")
    assert stories.pending(state) and stories.tick(state)
    assert "trough_boards" in conversation.knowledge(hessa)
    assert "share:trough_boards" in conversation.replies(state, hessa)
    learn(state, HESSA, fact="trough_boards")
    stories.tick(state)
    assert state["stories"]["stages"]["trough_water"] == ["sick", "cause"]
    assert not stories.pending(state)


def test_a_later_secret_stays_out_of_their_calls_until_taught():
    state = unit_state()
    darin = npc(state, DARIN)
    assert "needs_seal" not in str(persona.sheet_lines(state, darin))
    assert not any("needs the captain" in line for line in persona.sheet_lines(state, darin))


def test_cleaning_the_trough_sets_the_inn_right_and_moves_hessa_on():
    state = fresh_state(37, 53)
    assert state["objects"]["trough_hessa"]["mixture"][0]["name"] == "fouled"
    commit(
        state,
        judged(
            "other",
            effects=[{"kind": "clean", "target_id": "trough_hessa", "name": "fouled"}],
            seen_as="The stranger digs the rot out from under the trough and bails it clean.",
        ),
    )
    assert not state["objects"]["trough_hessa"]["mixture"]
    stories.tick(state)
    assert "clean" in state["stories"]["stages"]["trough_water"]
    hessa = cast.find(state["npcs"], HESSA)
    assert any("slow to pay" in line for line in persona.needs(hessa))  # Her ask moves on.
    assert any("water's sweet" in line for line in persona.sides(hessa))


def test_clean_water_handed_to_hessa_counts_and_foul_water_does_not():
    state = fresh_state(37, 53)
    state["objects"]["gourd_a"].update(
        holder_id=HESSA, given_by="player", water_l=1.0, mixture=[{"name": "fouled", "value": "x"}]
    )
    assert not stories._gifts(state, {"npc": [HESSA], "water": "clean"})
    state["objects"]["gourd_a"]["mixture"] = []
    assert stories._gifts(state, {"npc": [HESSA], "water": "clean"})


def test_a_step_in_one_quest_reaches_a_step_in_another_in_the_same_beat():
    state = unit_state()
    darin, oren = npc(state, DARIN), npc(state, OREN)
    learn(state, BREN, fact="oren_debt")
    stories.make_move(state, "forgive_oren_debt", 7)
    assert stories.tick(state)
    assert "answered" in state["stories"]["stages"]["oren_debt"]
    assert "clean_name" in state["stories"]["stages"]["darin_permit"]  # Crossing: Darin's name is clean now.
    assert any("squared" in line for line in persona.sides(darin))
    assert "cleared_quietly" in state["stories"]["milestones"]["oren_debt"]  # The "not" no longer blocks it.
    assert not any("owe the stranger" in line or "settled" in line for line in persona.sides(oren))  # Not told yet.
    clock._deliver_message(
        state, darin, oren, 5000, [], {"kind": "tell", "target": OREN, "message": "Square.", "event": 7}
    )
    stories.tick(state)
    assert any("settled" in line for line in persona.sides(oren))
    assert not stories.pending(state)


def test_someone_who_learns_of_an_ending_later_gets_it_once_without_being_made_to_think():
    state = unit_state()
    stories.make_move(state, "forgive_oren_debt", 9)
    stories.tick(state)
    jory = npc(state, JORY)
    assert not persona.story_facts(jory)
    cast.mind(jory).setdefault("memories", []).append(
        {
            "kind": "told",
            "event": 9,
            "summary": "Darin let Oren's debt go.",
            "at": 1,
            "clarity": "clear",
            "source": "heard_rumor",
            "severity": 0,
        }
    )
    state["pending_minds"] = []
    assert stories.tick(state)
    assert any("Dice and Debts" in line for line in persona.story_facts(jory))
    assert not any(p["npc_id"] == JORY for p in state["pending_minds"])  # Nothing of it is his to react to.
    stories.tick(state)
    assert len(persona.story_facts(jory)) == 1


def test_the_journal_shows_only_reached_steps_and_the_strangers_own_leads():
    state = unit_state()
    learn(state, HESSA, fact="sick_guests", lead="Hessa's guests keep falling sick.")
    learn(state, BREN, fact="captain_decides", lead="Only the captain decides.")
    stories.tick(state)
    inn = next(s for s in stories.page(state) if s["id"] == "trough_water")
    assert [s["text"] for s in inn["steps"]] == ["Hessa's guests keep falling sick after drinking from the trough."]
    assert inn["threads"] == [0]  # Her lead belongs to the quest; the captain's doesn't.
    assert all("rotting" not in s["text"] for s in inn["steps"])  # Never a step not yet reached.


def test_no_quest_ever_admits_the_stranger_by_itself():
    state = unit_state()
    for move_id in stories.MOVES:
        stories.make_move(state, move_id, 1)
    learn(state, HESSA, fact="sick_guests")
    stories.tick(state)
    assert not state.get("admitted") and not state.get("gate_open") and not state.get("inside_city")


def test_coming_up_to_someone_they_speak_first(world):  # noqa: F811
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    import commands

    with commands.open(state["run_id"], playable=False, stale=False) as cmd:
        hessa = cast.find(cmd.state["npcs"], HESSA)
        cmd.state["player"].update(x=hessa["x"] + 1, y=hessa["y"] + 1)
        cmd.save("test-position")
        state = cmd.state
    reply = post(world, state, "encounter/act", {"kind": "greet", "target_id": HESSA})
    entries = reply["round"]["entries"]
    assert entries[0]["who"] == "player" and entries[0]["text"] == "You come up to Hessa."
    assert any(e["who"] == HESSA for e in entries[1:])


def test_the_greeting_rule_rides_only_in_the_addressed_persons_call():
    state = unit_state()
    hessa, bren = npc(state, HESSA), npc(state, BREN)
    state["encounter"] = {
        "participants": [HESSA],
        "log": [{"kind": "greet", "text": "You come up to Hessa."}],
        "round": 1,
    }
    context = briefing.scene_context(state, hessa, [hessa], [bren], "", "The stranger has come up.")
    rules = {p["id"]: p["_rules"] for p in context["people"]}
    assert "greet" in rules[HESSA] and "greet" not in rules[BREN]


# --- The quests' shape (the user's rules: 5 or more steps, several ways each, intertwined) ---------------------------

QUESTS = [s["id"] for s in stories.running({"scenario": "village"})]  # Every quest the village runs.
OPEN = ("given", "seen_demonstration", "treated", "installed", "clean", "made", "deal", "move", "reached", "told")


def _owners():
    owners = {}
    for npc_id, card in cast.CARDS.items():
        for fact_id in card.get("knowledge", {}):
            owners.setdefault(f"fact:{fact_id}", set()).add(npc_id)
        for secret in card.get("secrets", []):
            owners.setdefault(f"secret:{secret['id']}", set()).add(npc_id)
    return owners


def _routes(spec, owners):
    """How many different ways a step can come true: distinct people who could tell it, and each open result."""
    kind = spec["kind"]
    if kind == "any":
        return sum(_routes(part, owners) for part in spec["of"])
    if kind == "learned":
        return len(set().union(*(owners.get(key, set()) for key in spec["any"])))
    if kind == "all":
        return min(_routes(part, owners) for part in spec["of"] if part["kind"] != "not")
    return 2 if kind in ("given", "seen_demonstration", "treated", "installed", "clean", "made") else 1


def _refs(spec):
    if isinstance(spec, dict):
        yield spec
        for value in spec.values():
            yield from _refs(value)
    elif isinstance(spec, list):
        for value in spec:
            yield from _refs(value)


def test_every_quest_has_five_steps_each_with_several_ways():
    owners = _owners()
    problems = []
    for quest_id in QUESTS:
        quest = stories.STORIES[quest_id]
        if len(quest["stages"]) < 5:
            problems.append(f"{quest_id}: {len(quest['stages'])} steps")
        for stage in quest["stages"]:
            if _routes(stage["when"], owners) < 2:
                problems.append(f"{quest_id}/{stage['id']}: one way only")
    assert not problems, problems


def test_every_quest_reference_resolves_and_every_later_thing_is_taught():
    owners, problems, taught = _owners(), [], set()
    for quest in stories.STORIES.values():
        for spec in _refs(quest):
            if spec.get("kind") == "learned":
                problems += [f"{quest['id']}: unknown {k}" for k in spec["any"] if k not in owners]
            if spec.get("kind") == "move" and spec["id"] not in stories.MOVES:
                problems.append(f"{quest['id']}: unknown move {spec['id']}")
            if spec.get("kind") == "reached":
                named = stories.part(
                    spec["story"], "stage" if spec.get("stage") else "outcome", spec.get("stage") or spec.get("outcome")
                )
                problems += [] if named else [f"{quest['id']}: unknown step {spec}"]
            if spec.get("kind") == "teach":
                taught.add(spec.get("fact") or spec.get("secret"))
            if spec.get("kind") == "side":
                problems += [] if len(spec["text"]) <= 240 else [f"{quest['id']}: side too long for {spec['npc']}"]
        for text in quest.get("sides", {}).values():
            problems += [] if len(text) <= 240 else [f"{quest['id']}: opening side too long"]
        for text in quest.get("needs", {}).values():
            problems += [] if len(text) <= 160 else [f"{quest['id']}: opening need too long"]
    for card in cast.CARDS.values():
        later = [k for k, f in card.get("knowledge", {}).items() if f.get("later")]
        later += [s["id"] for s in card.get("secrets", []) if s.get("later")]
        problems += [f"{card['id']}: {k} is never taught" for k in later if k not in taught]
    assert not problems, problems


def test_every_quest_crosses_into_another():
    for quest_id in QUESTS:
        quest = stories.STORIES[quest_id]
        people = {quest["people"]["owner"], *quest["people"].get("helps", []), *quest["people"].get("opposes", [])}
        assert len(people) >= 2, quest_id
        crossings = [s for s in _refs(quest) if s.get("kind") == "reached" and s["story"] != quest_id]
        crossings += [
            s for s in _refs(quest) if s.get("kind") == "move" and stories.MOVES[s["id"]]["story"] != quest_id
        ]
        others = {o["people"]["owner"] for o in stories.STORIES.values() if o["id"] != quest_id}
        crossings += [s for s in _refs(quest) if s.get("kind") in ("side", "need") and s["npc"] in others]
        assert crossings, f"{quest_id} touches no other quest"


def test_warmth_held_to_kades_knee_eases_it_and_he_feels_it():
    """Live (D-67): a warm stone wrapped in wool, held to Kade's knee, counted for nothing; soothe eases an ache."""
    state = fresh_state()
    kade = cast.find(state["npcs"], KADE)
    state["player"].update(x=kade["x"] + 1, y=kade["y"])
    state["objects"]["stone_b"].update(holder_id="player", temperature="hot")
    soothe = {"kind": "soothe", "target_id": KADE, "name": "ache", "other_id": "stone_b"}
    commit(state, judged("other", effects=[soothe], seen_as="The stranger holds a warm stone to Kade's knee."))
    assert any(c["kind"] == "ache" and c["treated"] for c in kade["conditions"])
    stories.tick(state)
    assert "eased" in state["stories"]["stages"]["kade_knees"]
    assert "eased" in state["stories"]["milestones"]["kade_knees"]
    assert any("eased your knees" in line for line in persona.sides(kade))
