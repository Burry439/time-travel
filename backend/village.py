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
AGENDA_EVERY_MS = 90_000  # How often a free person reconsiders their day...
TICK_MS = 30_000  # ...rounded to a shared tick, so several decide in one request.
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
        player = state["player"]
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
    return options


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
    plan = options[choice]["plan"]
    controller = npc.get("controller") or {}
    if plan["kind"] == "routine" or not controller:
        minds._set_job(npc, None, now)
        my_mind["doing"] = controller.get("goal")
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
    return {"npc_id": npc["id"], "agenda": choice, "mood": my_mind.get("mood"), "doing": my_mind.get("doing")}


def schedule(state: dict, npcs: list[dict], now: int) -> None:
    """Queue agenda beats (on a shared tick) and meetings for people who arrived or bumped into each other."""
    for index, npc in enumerate(npcs):
        if not free(state, npc):
            continue
        my_mind = minds.mind(npc)
        my_mind.setdefault("mood", persona.mood(npc))  # So everyone (and the client) can see how they seem.
        due = my_mind.get("next_agenda_at")
        if due is None:  # Staggered first beats, so the village doesn't all decide at once.
            my_mind["next_agenda_at"] = _tick(30_000 + index * 9_000)
        elif now >= due:
            minds.add_pending(state, npc["id"], "agenda", "time to decide what next")
            my_mind["next_agenda_at"] = _tick(now + AGENDA_EVERY_MS)
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


def _tick(ms: int) -> int:
    return -(-ms // TICK_MS) * TICK_MS


# --- Meetings: two people talk, and news travels ---------------------------------------------------

def topics(state: dict, a: dict, b: dict) -> dict[str, dict]:
    """What A could bring up with B: news B hasn't heard, the stranger, a worry, an opinion, small talk."""
    options: dict[str, dict] = {}
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
    if goals:
        options["worry"] = {"description": f"{a['name']} talks about what's on their mind: {goals[0].lower()}.",
                            "fact": goals[0], "kind": "worry"}
    for other_id, view in persona.opinions(a).items():
        other = minds.find(state["npcs"], other_id)
        if other and other_id != b["id"] and abs(view["warmth"]) >= 0.4:
            options[f"opinion:{other_id}"] = {"description": f"{a['name']} tells {b['name']} what they think of "
                                                             f"{other['name']}: {view['text']}.",
                                              "fact": f"{other['name']}: {view['text']}", "kind": "opinion",
                                              "about": other_id, "warmth": view["warmth"]}
    options["small_talk"] = {"description": f"{a['name']} passes the time of day with {b['name']}.",
                             "fact": "the weather, work and the day", "kind": "small_talk"}
    return options


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


def apply_meeting(state: dict, a: dict, b: dict, answers: dict, lines: tuple[str, str] | None, now: int) -> dict:
    """Commit what was said: news or hearsay passes to B, opinions shift, and the stranger may overhear."""
    options = topics(state, a, b)
    choice = (answers.get("topic") or {}).get("choice")
    choice = choice if choice in options else "small_talk"
    topic, believed, level = options[choice], _believes(answers), _level(answers)
    if topic["kind"] == "news":
        memory = topic["memory"]
        told = {**{k: memory.get(k) for k in ("kind", "severity", "short", "victim", "item", "works")},
                "event": memory.get("event"), "clarity": "told", "source": f"told_by:{a['id']}", "at": now,
                "summary": f"{a['name']} told them: {memory['summary']}", "doubted": not believed}
        minds.remember(b, told)
        if memory.get("severity", 0) >= 2 and believed:
            minds.mind(b)["rethinks"] = 0
            minds.add_pending(state, b["id"], "decide", f"told by {a['name']}")
    elif topic["kind"] == "stranger":
        heard = persona.knows(b).setdefault("heard", [])
        heard.append({"from": a["id"], "from_name": a["name"], "text": topic["fact"], "at": now, "doubted": not believed})
        del heard[:-6]
        name = persona.knows(a).get("name") or persona.knows(a).get("heard_name")
        if name and believed and not persona.knows(b).get("name"):
            persona.knows(b)["heard_name"] = name
        view_a, view_b = minds.regard(a), minds.regard(b)
        told_by = view_b.setdefault("heard_from", [])
        if believed and a["id"] not in told_by:  # One person's view of the stranger rubs off a little.
            told_by.append(a["id"])
            if view_a["trust"] >= 0.5:
                view_b["trust"] = round(min(1.0, view_b["trust"] + HEARSAY_SHIFT), 3)
            if view_a["suspicion"] >= 0.6:
                view_b["suspicion"] = round(min(1.0, view_b["suspicion"] + HEARSAY_SHIFT), 3)
    elif topic["kind"] == "opinion" and believed:
        feelings = persona.opinions(b)
        if topic["about"] in feelings:
            view = feelings[topic["about"]]
            view["warmth"] = round(max(-1.0, min(1.0, view["warmth"] + (0.1 if topic["warmth"] > 0 else -0.1))), 2)
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
            "believed": believed, "reaction": REACTION_LEVELS[level], "voiced": bool(lines), "learned": learned}
