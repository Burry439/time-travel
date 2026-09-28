"""The village's own life (GDD D-37): Jev chooses each person's next move in their day, and people
meet and pass news between them, whether or not the stranger is watching.

Code builds every option from the character sheet and the world (a task at a real place, a visit to
someone they know, a look at the stranger, a rest, or carrying on with their round) and applies every
effect: the walk there, a memory passed on, a warmer or cooler opinion. Jev only chooses among them.
The authored routines stay as the fallback whenever Jev can't or needn't decide.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import minds
import npc_sim
import persona

PLACES = json.loads((Path(__file__).resolve().parents[1] / "data" / "places.json").read_text(encoding="utf-8"))["places"]
AGENDA_GAP_MS = 20_000  # Something fresh makes a free person reconsider their day, at most this often (D-39).
MEET_GAP_MS = 120_000  # Nobody stops for another chat within this long of their last one.
MEET_CELLS = 3.0  # Close enough to fall into conversation.
VISIT_REACH = 3.0
MIN_GATE_GUARDS = 2  # The gate is never left with fewer guards than this.
GATE_GUARDS = ("npc_roderic_vale", "npc_bren_marr", "npc_oren_dast")
CHATTER_PER_MINUTE = 2  # Voiced meetings (only when the stranger can see them).
OVERHEAR_CELLS = 5.0
WARMTH_SHIFTS = [-0.1, -0.05, 0.0, 0.05, 0.1]
REACTION_LEVELS = ["Put off by it", "A little cooler", "Unmoved", "A little warmer", "Glad of it"]
HEARSAY_SHIFT = 0.05  # How much one person's view of the stranger rubs off on another (once per teller).
CHAT_MS = 8_000


def place_name(place_id: str) -> str:
    return PLACES[place_id]["name"]


def _village(state: dict) -> dict:
    return state.setdefault("village", {"chatter_at": []})


def free(state: dict, npc: dict) -> bool:
    """Alive, not busy with something they decided, and not face to face with the stranger."""
    if not npc.get("alive", True) or (npc.get("mind") or {}).get("job"):
        return False
    return npc["id"] not in ((state.get("encounter") or {}).get("participants") or [])


def _world_holds(state: dict, condition: dict | None) -> bool:
    placed = (condition or {}).get("installed")
    return bool(state["objects"].get(placed, {}).get("installed_in")) if placed else True


def tasks(state: dict, npc: dict) -> list[dict]:
    """The card's tasks that make sense in the world as it is (the beam once raised, and so on)."""
    return [t for t in minds.card(npc).get("tasks", [])
            if _world_holds(state, t.get("when")) and not (t.get("unless") and _world_holds(state, t["unless"]))]


def at_gate(npc: dict) -> bool:
    controller = npc.get("controller") or {}
    target = tuple(controller.get("destination") or (npc["x"], npc["y"]))
    return npc["x"] <= 56 and npc["x"] >= 40 and npc["y"] <= 20 and target[1] <= 20


def gate_cover(state: dict, leaving: dict) -> int:
    """Gate guards who would still be at the gate if this one left."""
    return sum(1 for g in state["npcs"] if g["id"] in GATE_GUARDS and g["id"] != leaving["id"]
               and g.get("alive", True) and at_gate(g))


def agenda_options(state: dict, npc: dict) -> dict[str, dict]:
    """Everything this person could sensibly do next with their day: {key: {description, plan}}."""
    name = npc["name"]
    bound = npc["id"] in GATE_GUARDS and gate_cover(state, npc) < MIN_GATE_GUARDS
    goal = (npc.get("controller") or {}).get("goal") or "their usual round"
    options = {"carry_on": {"description": f"{name} carries on as usual ({goal}).", "plan": {"kind": "routine"}}}
    for task in tasks(state, npc):
        if bound and not PLACES[task["place"]].get("gate"):
            continue
        options[f"task:{task['id']}"] = {"description": f"{name} goes to {place_name(task['place'])}: "
                                                        f"{task['doing']}.", "plan": {"kind": "task", **task}}
    if not bound:
        feelings = persona.opinions(npc)
        for other in state["npcs"]:
            view = feelings.get(other["id"])
            if view is None or view["warmth"] < -0.2 or not free(state, other) or \
                    math.dist(minds._cell(other), minds._cell(npc)) > 45:
                continue
            options[f"visit:{other['id']}"] = {
                "description": f"{name} goes over to talk with {other['name']} ({view['text']}), who is "
                               f"{persona.doing(other)}.", "plan": {"kind": "visit", "target": other["id"]}}
        grievance = _grievance(npc)
        if grievance:  # Something to pass on: tell family or a guard first.
            listeners = sorted((o for o in state["npcs"] if o["id"] != npc["id"] and free(state, o)
                                and not minds.knows(o, grievance.get("event"))),
                               key=lambda o: (not minds.is_family(npc, o["id"]), not minds.card(o).get("guard"),
                                              math.dist(minds._cell(o), minds._cell(npc))))
            for other in listeners[:2]:
                options[f"tell:{other['id']}"] = {
                    "description": f"{name} goes to tell {minds.relation(npc, other['id']) or other['name']} what "
                                   f"happened: {grievance['summary']}", "plan": {"kind": "visit", "target": other["id"]}}
        wronged = next((m for m in minds.mind(npc)["memories"] if m["kind"] in minds.CRIME_KINDS
                        and m.get("victim") == npc["id"] and m.get("source") == "victim"), None)
        player = state["player"]
        if wronged and player.get("alive", True) and not minds.card(npc).get("guard") and                 state.get("sim_time_ms", 0) - minds.mind(npc).get("confronted_at", -10**9) > 60_000:
            options["confront"] = {"description": f"{name} goes and has it out with the stranger: {wronged['summary']}",
                                   "plan": {"kind": "confront"}}
        met = persona.knows(npc).get("episodes") or minds.mind(npc).get("met")
        if player.get("alive", True) and not state.get("inside_city") and not minds.card(npc).get("guard") \
                and math.dist(minds.player_cell(state), minds._cell(npc)) <= 25:
            options["stranger"] = {"description": f"{name} wanders over to see what the stranger "
                                                  f"{'is up to now' if met else 'is up to'}.",
                                   "plan": {"kind": "stranger"}}
        if not minds.card(npc).get("guard"):
            options["rest"] = {"description": f"{name} takes a rest by the inn.",
                               "plan": {"kind": "task", "place": "inn_side", "activity": "wait", "dwell_s": 50,
                                        "doing": "resting a while by the inn"}}
    last = minds.mind(npc).get("last_agenda", "")
    if last.startswith(("visit:", "tell:", "stranger", "confront")):  # Not the same errand twice in a row.
        options.pop(last, None)
    return options


def _grievance(npc: dict) -> dict | None:
    """The most serious thing this person knows about the stranger that is worth telling someone."""
    serious = [m for m in minds.mind(npc)["memories"] if m.get("severity", 0) >= 2 and m.get("event") is not None
               and not m.get("doubted")]
    return max(serious, key=lambda m: m["severity"], default=None)


def agenda_brief(state: dict, npc: dict, prefix: str = "") -> tuple[str, dict]:
    name = npc["name"]
    minutes = state.get("sim_time_ms", 0) // 60_000
    text = (minds._situation(state, npc) + f"\nIt is {minutes} minutes into the day. {name} is free to decide "
            f"what to do next: carry on, see to something that matters to them, look up someone they know, or rest.")
    questions = {
        f"{prefix}agenda": {"type": "choice",
                            "criteria": {k: o["description"] for k, o in agenda_options(state, npc).items()},
                            "instructions": f"Given who {name} is, what they want and how they feel, what does {name} "
                                            f"do next? People mostly keep to their work, but not always."},
        f"{prefix}mood": {"type": "choice", "criteria": {m: f"{name} feels {m}" for m in persona.MOODS},
                          "instructions": f"How does {name} feel at the moment?"},
    }
    tell = next((k for k in agenda_options(state, npc) if k.startswith("tell:")), None)
    if tell:  # A yes/no is more reliable than hoping one important option wins a long choice.
        questions[f"{prefix}tell_someone"] = {"type": "noul", "instructions": (
            f"Would {name} go now and tell someone what happened? "
            f"({agenda_options(state, npc)[tell]['description']})")}
    return text, questions


def apply_agenda(state: dict, npc: dict, answers: dict, now: int) -> dict:
    """Turn the chosen option into a plan: a walk somewhere, and what they're doing when they get there."""
    my_mind = minds.mind(npc)
    mood = (answers.get("mood") or {}).get("choice")
    if mood in persona.MOODS:
        my_mind["mood"] = mood
    options = agenda_options(state, npc)
    choice = (answers.get("agenda") or {}).get("choice")
    choice = choice if choice in options else "carry_on"
    tell = next((k for k in options if k.startswith("tell:")), None)
    if tell and choice != "confront" and float((answers.get("tell_someone") or {}).get("noul", 0.0)) >= 0.5:
        choice = tell
    plan = options[choice]["plan"]
    controller = npc.get("controller") or {}
    if plan["kind"] == "routine" or not controller:
        minds._set_job(npc, None, now)
        my_mind["doing"] = controller.get("goal")
    elif plan["kind"] == "confront":
        my_mind["confronted_at"] = now
        wronged = next((m for m in minds.mind(npc)["memories"] if m.get("victim") == npc["id"]
                        and m["kind"] in minds.CRIME_KINDS), {})
        # Their own grievance in their own words (the confront bank speaks up for someone else).
        own = minds._lines(state, npc, "demand_payment", minds.slots(state, npc)) \
            if wronged.get("kind") == "theft" else []
        line_id, line = own[0] if own else (None, "You! You'll answer for what you did to me.")
        minds._set_job(npc, {"kind": "approach", "target": "player", "stop": 2.0, "speed": "walk", "then": "confront",
                             "line": line, "line_id": line_id}, now)
        my_mind["doing"] = "going to have it out with the stranger"
    elif plan["kind"] == "stranger":
        minds._set_job(npc, {"kind": "approach", "target": "player", "stop": 3.0, "speed": "walk", "then": None,
                             "line": None, "line_id": None}, now)
        my_mind["doing"] = "going to see what the stranger is up to"
    else:
        blocked = npc_sim.blocked_cells(minds.crafting.m2._GEOMETRY)
        try:
            if plan["kind"] == "visit":
                other = minds.find(state["npcs"], plan["target"])
                path = npc_sim.route(minds._cell(npc), minds._cell(other), blocked)[:-1]
                controller.update(visit=other["id"], arrive_activity="wait", dwell_ms=30_000)
                my_mind["doing"] = f"on the way to see {other['name']}"
            else:
                path = npc_sim.route(minds._cell(npc), tuple(PLACES[plan["place"]]["cell"]), blocked)
                controller.update(visit=None, arrive_activity=plan["activity"], dwell_ms=plan["dwell_s"] * 1000)
                my_mind["doing"] = plan["doing"]
        except ValueError:  # No way there right now: carry on as usual instead.
            minds._set_job(npc, None, now)
            my_mind["doing"] = controller.get("goal")
            return {"npc_id": npc["id"], "agenda": "carry_on", "mood": my_mind.get("mood"), "doing": my_mind["doing"]}
        controller.update(source="agenda", path=path, destination=list(path[-1]) if path else [npc["x"], npc["y"]],
                          activity="walk" if path else controller["arrive_activity"], step_carry_ms=0,
                          next_at_ms=now + (0 if path else controller["dwell_ms"]))
    my_mind["last_agenda"] = choice
    return {"npc_id": npc["id"], "agenda": choice, "mood": my_mind.get("mood"), "doing": my_mind.get("doing")}


def schedule(state: dict, npcs: list[dict], now: int) -> None:
    """Jev only when something happens (D-39): a free person whose mind is fresh (news, a memory, a storyline,
    the stranger coming into view) reconsiders their day. Otherwise the routine goes on by code. Also queues
    meetings for people who arrived on a visit or bumped into someone they know."""
    for npc in npcs:
        my_mind = minds.mind(npc)
        my_mind.setdefault("mood", persona.mood(npc))  # So everyone (and the client) can see how they seem.
        seen = near_stranger(state, npc, minds.SIGHT_CELLS)
        if seen and not my_mind.get("stranger_seen"):
            my_mind["fresh"] = my_mind.get("fresh") or "the stranger came into view"
        my_mind["stranger_seen"] = seen
        if not free(state, npc):
            continue
        if my_mind.get("fresh") and now >= my_mind.get("next_agenda_at", 0) and \
                not any(p["npc_id"] == npc["id"] for p in state.get("pending_minds", [])):
            minds.add_pending(state, npc["id"], "agenda", str(my_mind["fresh"]))
            my_mind["fresh"] = None
            my_mind["next_agenda_at"] = now + AGENDA_GAP_MS
        controller = npc.get("controller") or {}
        visiting = controller.get("visit")
        if visiting and controller.get("activity") != "walk":
            controller["visit"] = None
            other = minds.find(npcs, visiting)
            if other and free(state, other) and math.dist(minds._cell(other), minds._cell(npc)) <= VISIT_REACH:
                _stop_to_talk(state, npc, other, now)
            else:
                my_mind["doing"] = f"looking for {other['name'] if other else 'someone'}, who has gone"
    idle = [n for n in npcs if free(state, n) and (n.get("controller") or {}).get("activity") != "walk"
            and now - minds.mind(n).get("last_met", -MEET_GAP_MS) >= MEET_GAP_MS]
    for a in idle:
        for b in idle:
            if a["id"] < b["id"] and math.dist(minds._cell(a), minds._cell(b)) <= MEET_CELLS and \
                    (b["id"] in persona.opinions(a) or a["id"] in persona.opinions(b)) and \
                    not any(p["kind"] == "meet" and p["npc_id"] in (a["id"], b["id"]) for p in state.get("pending_minds", [])):
                _stop_to_talk(state, a, b, now)


def _stop_to_talk(state: dict, a: dict, b: dict, now: int) -> None:
    """They fall into conversation: both stay where they are until it has been decided what they talk about."""
    minds.add_pending(state, a["id"], "meet", b["id"])
    for person, other in ((a, b), (b, a)):
        controller = person.get("controller") or {}
        if controller.get("activity") != "walk":
            controller["next_at_ms"] = max(controller.get("next_at_ms", 0), now + 2 * CHAT_MS)
        minds.mind(person)["chatting_with"] = {"id": other["id"], "until": now + 2 * CHAT_MS}


# --- Meetings: two people talk, and news travels ---------------------------------------------------

def _told(a: dict, b: dict) -> list[str]:
    """Topics A has already raised with B (nobody tells the same person the same thing twice)."""
    return minds.mind(a).setdefault("told", {}).setdefault(b["id"], [])


def topics(state: dict, a: dict, b: dict) -> dict[str, dict]:
    """What A could bring up with B: news B hasn't heard, the stranger, a worry, an opinion, small talk."""
    options: dict[str, dict] = {}
    told = _told(a, b)
    for memory in minds.mind(a)["memories"]:
        event = memory.get("event")
        if event is None or minds.knows(b, event) or (memory["kind"] == "talk" and memory.get("severity", 0) < 1):
            continue
        options[f"news:{event}"] = {"description": f"{a['name']} tells {b['name']}: {memory['summary']}",
                                    "fact": memory["summary"], "kind": "news", "memory": memory}
    known = persona.knows(a)
    latest = (known["episodes"][-1]["text"] if known["episodes"] else None) or \
        (" ".join(known["notes"][-2:]) if known["notes"] else None)
    heard_from_a = [h for h in persona.knows(b).get("heard", []) if h["from"] == a["id"]]
    if latest and (not heard_from_a or heard_from_a[-1]["text"] != latest):
        options["stranger"] = {"description": f"{a['name']} tells {b['name']} about the stranger: {latest}",
                               "fact": latest, "kind": "stranger"}
    goals = minds.card(a).get("goals") or []
    fresh = [i for i in range(len(goals)) if f"worry:{i}" not in told]
    if fresh:
        goal = goals[fresh[0]]
        options["worry"] = {"description": f"{a['name']} talks about what's on their mind: {goal[0].lower() + goal[1:]}.",
                            "fact": goal, "kind": "worry", "told_key": f"worry:{fresh[0]}"}
    for other_id, view in persona.opinions(a).items():
        other = minds.find(state["npcs"], other_id)
        if other and other_id != b["id"] and abs(view["warmth"]) >= 0.4 and f"opinion:{other_id}" not in told:
            options[f"opinion:{other_id}"] = {"description": f"{a['name']} tells {b['name']} what they think of "
                                                             f"{other['name']}: {view['text']}.",
                                              "fact": f"{other['name']}: {view['text']}", "kind": "opinion",
                                              "about": other_id, "warmth": view["warmth"]}
    options["small_talk"] = {"description": f"{a['name']} passes the time of day with {b['name']}.",
                             "fact": "the weather, work and the day", "kind": "small_talk"}
    return options


def has_news(state: dict, a: dict, b: dict) -> bool:
    """Whether a meeting is worth asking Jev about: either has something to pass on (else it's a nod, by code)."""
    return bool(news_pick(state, a, b) or news_pick(state, b, a) or minds.mind(a).get("fresh")
                or minds.mind(b).get("fresh"))


def news_pick(state: dict, a: dict, b: dict) -> str | None:
    """The most important thing A could pass on to B: the most serious news, else word of the stranger."""
    options = topics(state, a, b)
    news = sorted((k for k in options if options[k]["kind"] == "news"),
                  key=lambda k: -options[k]["memory"].get("severity", 0))
    return news[0] if news else ("stranger" if "stranger" in options else None)


def chosen_topic(state: dict, a: dict, b: dict, answers: dict) -> str:
    """Jev's topic, unless A (as Jev believes) would pass on the news first: a yes/no is more reliable than
    hoping one important option wins a long choice (GDD M5 lesson)."""
    options = topics(state, a, b)
    pick = news_pick(state, a, b)
    if pick and float((answers.get("tells") or {}).get("noul", 0.0)) >= 0.5:
        return pick
    choice = (answers.get("topic") or {}).get("choice")
    return choice if choice in options else "small_talk"


def meet_brief(state: dict, a: dict, b: dict, prefix: str = "") -> tuple[str, dict]:
    view_ab, view_ba = persona.opinions(a).get(b["id"]), persona.opinions(b).get(a["id"])
    text = (minds._situation(state, a) + f"\n\n{a['name']} has fallen into conversation with {b['name']}, the "
            f"{minds.card(b)['role']}. " + (f"{a['name']} {persona.warmth_words(view_ab['warmth'])} {b['name']} "
                                            f"({view_ab['text']}). " if view_ab else "")
            + (f"{b['name']} {persona.warmth_words(view_ba['warmth'])} {a['name']} ({view_ba['text']}). " if view_ba else "")
            + f"{b['name']}'s mood: {persona.mood(b)}; {b['name']} likes {minds.card(b).get('likes', 'little')}.")
    questions = {
        f"{prefix}topic": {"type": "choice", "criteria": {k: o["description"] for k, o in topics(state, a, b).items()},
                           "instructions": f"What does {a['name']} bring up with {b['name']}? People pass on news "
                                           f"that matters to them and to the listener."},
        f"{prefix}reaction": {"type": "score", "criteria": REACTION_LEVELS,
                              "instructions": f"How does {b['name']} take it, and {a['name']} for saying it?"},
        f"{prefix}believes": {"type": "noul", "instructions": f"Does {b['name']} believe what {a['name']} tells them?"},
    }
    pick = news_pick(state, a, b)
    if pick:
        questions[f"{prefix}tells"] = {"type": "noul", "instructions": (
            f"Would {a['name']} bring this up with {b['name']} now: {topics(state, a, b)[pick]['description']} "
            f"People pass on trouble, crimes and word of strangers to those it concerns.")}
    back = news_pick(state, b, a)
    if back:  # Conversations go both ways: the listener may have news of their own.
        questions[f"{prefix}tells_back"] = {"type": "noul", "instructions": (
            f"Would {b['name']} in turn bring this up with {a['name']}: {topics(state, b, a)[back]['description']}")}
    return text, questions


def near_stranger(state: dict, npc: dict, cells: float) -> bool:
    here = minds.player_cell(state)
    return state["player"].get("alive", True) and math.dist(minds._cell(npc), here) <= cells \
        and minds.line_of_sight(minds._cell(npc), here)


def chatter_allowed(state: dict, a: dict, now: int) -> bool:
    recent = [t for t in _village(state)["chatter_at"] if now - t < 60_000]
    return near_stranger(state, a, minds.SIGHT_CELLS) and len(recent) < CHATTER_PER_MINUTE


def chatter_context(state: dict, a: dict, b: dict, topic: dict, answers: dict) -> dict:
    level = _level(answers)
    return {"speaker": {"name": a["name"], "role": minds.card(a)["role"], **persona.voice_sheet(state, a)},
            "listener": {"name": b["name"], "role": minds.card(b)["role"], **persona.voice_sheet(state, b)},
            "topic": topic["description"],
            "listener_reaction": f"{REACTION_LEVELS[level]}; "
                                 f"{'believes it' if _believes(answers) else 'does not quite believe it'}"}


def fallback_chatter(a: dict, b: dict, topic: dict, answers: dict) -> tuple[str, str]:
    opening = {"news": f"Did you hear? {topic['fact']}", "stranger": f"That stranger again. {topic['fact']}",
               "worry": f"I keep thinking about it: {topic['fact'].lower()}.",
               "opinion": f"Between us, {topic['fact']}.", "small_talk": "Long day, isn't it?"}[topic["kind"]]
    reply = "Is that so." if _believes(answers) else "I'll believe that when I see it."
    return opening[:200], reply


def _level(answers: dict) -> int:
    score = (answers.get("reaction") or {}).get("score")
    return 2 if score is None else max(0, min(4, int(round(float(score)))))


def _believes(answers: dict) -> bool:
    return float((answers.get("believes") or {}).get("noul", 1.0)) >= 0.5


def _pass_on(state: dict, teller: dict, listener: dict, topic: dict, believed: bool, now: int) -> None:
    """News becomes the listener's memory ("told by"); word of the stranger becomes hearsay (and a name)."""
    if topic["kind"] == "news":
        memory = topic["memory"]
        told = {**{k: memory.get(k) for k in ("kind", "severity", "short", "victim", "item", "works")},
                "event": memory.get("event"), "clarity": "told", "source": f"told_by:{teller['id']}", "at": now,
                "summary": f"{teller['name']} told them: {memory['summary']}", "doubted": not believed}
        minds.remember(listener, told)
        if memory.get("severity", 0) >= 2 and believed:
            minds.mind(listener)["rethinks"] = 0
            minds.add_pending(state, listener["id"], "decide", f"told by {teller['name']}")
    elif topic["kind"] == "stranger":
        heard = persona.knows(listener).setdefault("heard", [])
        heard.append({"from": teller["id"], "from_name": teller["name"], "text": topic["fact"], "at": now,
                      "doubted": not believed})
        del heard[:-6]
        name = persona.knows(teller).get("name") or persona.knows(teller).get("heard_name")
        if name and believed and not persona.knows(listener).get("name"):
            persona.knows(listener)["heard_name"] = name
        view_t, view_l = minds.regard(teller), minds.regard(listener)
        told_by = view_l.setdefault("heard_from", [])
        if believed and teller["id"] not in told_by:  # One person's view of the stranger rubs off a little.
            told_by.append(teller["id"])
            if view_t["trust"] >= 0.5:
                view_l["trust"] = round(min(1.0, view_l["trust"] + HEARSAY_SHIFT), 3)
            if view_t["suspicion"] >= 0.6:
                view_l["suspicion"] = round(min(1.0, view_l["suspicion"] + HEARSAY_SHIFT), 3)
    elif topic["kind"] == "opinion" and believed:
        feelings = persona.opinions(listener)
        if topic["about"] in feelings:
            view = feelings[topic["about"]]
            view["warmth"] = round(max(-1.0, min(1.0, view["warmth"] + (0.1 if topic["warmth"] > 0 else -0.1))), 2)


def apply_meeting(state: dict, a: dict, b: dict, answers: dict, lines: tuple[str, str] | None, now: int) -> dict:
    """Commit what was said: news or hearsay passes both ways, opinions shift, and the stranger may overhear."""
    options = topics(state, a, b)
    choice = chosen_topic(state, a, b, answers)
    topic, believed, level = options[choice], _believes(answers), _level(answers)
    if choice != "small_talk":
        told = _told(a, b)
        told.append(topic.get("told_key", choice))
        del told[:-12]
    _pass_on(state, a, b, topic, believed, now)
    back = news_pick(state, b, a)
    returned = None
    if back and float((answers.get("tells_back") or {}).get("noul", 0.0)) >= 0.5:
        returned = topics(state, b, a)[back]
        _told(b, a).append(back)
        _pass_on(state, b, a, returned, True, now)
    shift = WARMTH_SHIFTS[level]
    for person, other, amount in ((b, a, shift), (a, b, shift / 2)):
        feelings = persona.opinions(person)
        if other["id"] in feelings:
            view = feelings[other["id"]]
            view["warmth"] = round(max(-1.0, min(1.0, view["warmth"] + amount)), 2)
        elif amount:
            feelings[other["id"]] = {"text": f"{other['name']} the {minds.card(other)['role']}",
                                     "warmth": round(amount, 2)}
    learned = []
    for person, other in ((a, b), (b, a)):
        my_mind = minds.mind(person)
        my_mind["last_met"] = now
        my_mind["chatting_with"] = {"id": other["id"], "until": now + CHAT_MS}
        controller = person.get("controller") or {}
        if controller.get("activity") != "walk":
            controller["next_at_ms"] = max(controller.get("next_at_ms", 0), now + CHAT_MS)
    if lines:
        _village(state)["chatter_at"] = [t for t in _village(state)["chatter_at"] if now - t < 60_000] + [now]
        minds.mind(a)["said"] = {"text": lines[0], "at": now, "key": f"{a['id']}:chat:{now}"}
        minds.mind(b)["said"] = {"text": lines[1], "at": now, "key": f"{b['id']}:chat:{now}", "after_ms": 2200}
        if near_stranger(state, a, OVERHEAR_CELLS):
            for person, line, other in ((a, lines[0], b), (b, lines[1], a)):
                learned.append({"npc_id": person["id"], "name": person["name"], "said": line,
                                "overheard": other["name"], "at": now})
    return {"npc_id": a["id"], "with": b["id"], "topic": choice, "about": topic["description"],
            "told_back": returned["description"] if returned else None,
            "believed": believed, "reaction": REACTION_LEVELS[level], "voiced": bool(lines), "learned": learned}
