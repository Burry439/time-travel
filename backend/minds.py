"""NPC minds: perception, memories, feelings, decisions and the actions that follow.

Code decides who could perceive an event, which actions are legal for each person, and what
those actions do over time. The decider role (Jev by default) only chooses among the legal
options and rates feelings, so an NPC can never do something the simulation can't represent.

Flow: a committed player act -> perceive() gives witnesses memories and queues them in
state["pending_minds"] -> the client calls /think -> decision_requests() -> the decider ->
apply_answers() starts jobs (flee, shout, report, confront, attack, help) -> advance_world()
moves people along their jobs each clock beat, which can queue more thinking (a guard who has
just been told, an attacker in reach of the player).
"""
from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path

import crafting
import npc_sim

ROOT = Path(__file__).resolve().parents[1]
CARDS: dict[str, dict] = json.loads((ROOT / "data" / "content" / "npc_cards.json").read_text(encoding="utf-8"))["npcs"]
GEOMETRY = json.loads((ROOT / "data" / "world_geometry.json").read_text(encoding="utf-8"))
WALLS = {(cx, cy) for b in GEOMETRY["buildings"] for x, y, w, h in [b["cells"]]
         for cx in range(x, x + w) for cy in range(y, y + h)}  # Buildings block sight; trees do not.
SIGHT_CELLS = 10.0
HEAR_SHOUT_CELLS = 16.0
MEMORY_LIMIT = 12
RUN_STEP_MS = 170
WALK_STEP_MS = 400
ATTACK_INTERVAL_MS = 2500
GIVE_UP_CELLS = 28.0
PLAYER_WOUND = 40
THINK_BATCH = 6  # People who can think in one /think call; the rest wait for the next.
ACTIVITY_WORDS = {"work": "working", "look": "keeping watch", "patrol": "patrolling", "wait": "waiting",
                  "walk": "walking", "conversation": "talking", "dead": "lying dead"}
FEAR_LEVELS = ["Not afraid", "Uneasy", "Afraid", "Terrified"]
ANGER_LEVELS = ["Calm", "Annoyed", "Angry", "Furious"]


# --- Small helpers ---------------------------------------------------------------------------

def card(npc: dict) -> dict:
    return CARDS.get(npc["id"], {"name": npc["name"], "role": npc["role"], "guard": False, "weapon": None,
                                 "combat": "no fighter", "personality": "", "values": "", "fears": "",
                                 "authority": ""})


def mind(npc: dict) -> dict:
    return npc.setdefault("mind", {"memories": [], "feelings": {"fear": 0.0, "anger": 0.0}, "job": None,
                                   "said": None})


def find(npcs: list[dict], npc_id: str) -> dict | None:
    return next((n for n in npcs if n["id"] == npc_id), None)


def player_cell(state: dict) -> tuple[int, int]:
    return state["player"]["x"], state["player"]["y"]


def _cell(npc: dict) -> tuple[int, int]:
    return npc["x"], npc["y"]


def line_of_sight(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if no building stands between the two cells (Bresenham line)."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while (x0, y0) != (x1, y1):
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy
        if (x0, y0) != (x1, y1) and (x0, y0) in WALLS:
            return False
    return True


def condition(health: float, alive: bool = True) -> str:
    if not alive:
        return "dead"
    return "unhurt" if health >= 100 else "wounded" if health > 30 else "badly wounded (near death)"


def add_pending(state: dict, npc_id: str, kind: str = "decide", why: str = "") -> None:
    pending = state.setdefault("pending_minds", [])
    if not any(p["npc_id"] == npc_id and p["kind"] == kind for p in pending):
        pending.append({"npc_id": npc_id, "kind": kind, "why": why})


def calm(state: dict) -> bool:
    """No one is reacting to the player: a safe point to rewind to."""
    if state.get("pending_minds") or not state["player"].get("alive", True):
        return False
    return not any((npc.get("mind") or {}).get("job") and npc["mind"]["job"]["kind"] in
                   ("attack", "report", "flee", "approach") for npc in state["npcs"])


def _say(npc: dict, text: str, now: int, state: dict, journal: list[dict]) -> None:
    mind(npc)["said"] = {"text": text, "at": now, "key": f"{npc['id']}:{now}:{len(journal)}"}
    if math.dist(_cell(npc), player_cell(state)) <= HEAR_SHOUT_CELLS:
        journal.append({"kind": "npc", "npc_id": npc["id"], "category": "heard",
                        "reason": f"{npc['name']}: “{text}”"})


# --- Perception --------------------------------------------------------------------------------

def _describe(state: dict, entry: dict) -> dict | None:
    """What an onlooker could see of a committed attempt, in plain words. None if nothing notable."""
    names = {n["id"]: n["name"] for n in state["npcs"]}
    harm = entry.get("harm")
    if entry.get("category") in ("success", "partial_success") and isinstance(harm, dict):
        victim = names.get(harm["target_id"], "someone")
        weapon = state["objects"].get(harm.get("weapon_id") or "", {}).get("name")
        how = f" with a {weapon}" if weapon else " with bare hands"
        verb = "threw a " + weapon + " at" if harm.get("method") == "thrown" and weapon else "attacked"
        outcome = {"killed": f"{victim} fell and did not get up.", "wounded": f"{victim} was hurt.",
                   "missed": f"The blow missed {victim}."}[harm["result"]]
        short = {"killed": f"killed {victim}", "wounded": f"attacked {victim}",
                 "missed": f"attacked {victim}"}[harm["result"]]
        text = f"The stranger {verb} {victim}{'' if 'threw' in verb else how}. {outcome}"
        return {"kind": "violence", "summary": text, "short": short, "victim": harm["target_id"],
                "severity": {"killed": 3, "wounded": 2, "missed": 1}[harm["result"]]}
    claims = entry.get("property") or []
    if entry.get("category") in ("success", "partial_success") and claims:
        claim = claims[0]
        owner = names.get(claim["owner_id"], "someone")
        verb = {"taken": "took", "used up": "used up", "used": "used"}.get(claim["how"], f"{claim['how']}")
        return {"kind": "theft", "summary": f"The stranger {verb} {owner}'s {claim['name']} without asking.",
                "short": f"stole {owner}'s {claim['name']}", "victim": claim["owner_id"], "severity": 1}
    return None


def perceive(state: dict, entry: dict) -> list[dict]:
    """Memories for everyone who could see what the player just did (and for the victim)."""
    seen = _describe(state, entry)
    if seen is None:
        return []
    here = player_cell(state)
    victim = find(state["npcs"], seen["victim"])
    perceptions = []
    for npc in state["npcs"]:
        if not npc.get("alive", True):
            continue
        near_player = math.dist(_cell(npc), here) <= SIGHT_CELLS and line_of_sight(_cell(npc), here)
        near_victim = victim is not None and math.dist(_cell(npc), _cell(victim)) <= SIGHT_CELLS \
            and line_of_sight(_cell(npc), _cell(victim))
        is_victim = npc["id"] == seen["victim"]
        if not (is_victim or near_player or near_victim):
            continue
        memory = {**{k: seen[k] for k in ("kind", "summary", "short", "victim", "severity")},
                  "at": state["sim_time_ms"], "event": entry.get("event_id"),
                  "source": "victim" if is_victim else "witnessed"}
        perceptions.append({"npc_id": npc["id"], "memory": memory})
    return perceptions


def apply_perceptions(state: dict, perceptions: list[dict]) -> None:
    for perception in perceptions:
        npc = find(state["npcs"], perception["npc_id"])
        if npc is None or not npc.get("alive", True):
            continue
        memories = mind(npc)["memories"]
        memories.append(perception["memory"])
        del memories[:-MEMORY_LIMIT]
        add_pending(state, npc["id"], "decide", perception["memory"]["source"])


# --- Deciding ------------------------------------------------------------------------------------

def legal_actions(state: dict, npc: dict) -> dict[str, str]:
    """Every option code can carry out for this person right now, described for the decider."""
    name, me = npc["name"], card(npc)
    options = {
        "carry_on": f"{name} ignores it and carries on with what they were doing.",
        "watch": f"{name} stays where they are and keeps a wary eye on the stranger.",
        "flee": f"{name} runs away from the stranger to somewhere safe.",
        "shout_for_help": f"{name} shouts loudly for help and for the guards, right where they are.",
    }
    if state["player"].get("alive", True):
        recently = (mind(npc).get("confronted_at") or -10**9) > state["sim_time_ms"] - 60_000
        if not recently:
            options["confront"] = f"{name} walks up to the stranger and demands an explanation."
        weapon = f" with their {me['weapon']}" if me.get("weapon") else " with bare hands"
        options["attack"] = f"{name} attacks the stranger{weapon} ({me.get('combat', 'no fighter')})."
    guards = sorted((g for g in state["npcs"] if g["id"] != npc["id"] and g.get("alive", True)
                     and card(g).get("guard")), key=lambda g: math.dist(_cell(g), _cell(npc)))
    for guard in guards[:2]:
        steps = round(math.dist(_cell(guard), _cell(npc)))
        options[f"report:{guard['id']}"] = (f"{name} goes to {guard['name']} the {card(guard)['role']} "
                                            f"(about {steps} steps away) and tells them what happened.")
    for memory in mind(npc)["memories"][-4:]:
        victim = find(state["npcs"], memory.get("victim") or "")
        if victim and victim["id"] != npc["id"] and victim.get("alive", True) and victim.get("health", 100) < 100:
            options[f"help:{victim['id']}"] = f"{name} goes to help {victim['name']}, who is hurt."
    return options


def _situation(state: dict, npc: dict) -> str:
    me, my_mind = card(npc), mind(npc)
    here = player_cell(state)
    steps = round(math.dist(_cell(npc), here))
    carried = [o["name"] for o in state["objects"].values() if o["holder_id"] == "player"]
    lines = [
        f"{me['name']} is the {me['role']} ({me.get('age', '?')}) in a small premodern town outside a walled city. "
        f"{me['personality']}",
        f"Values: {me['values']}. Fears: {me['fears']}.",
        f"Authority: {me['authority']}",
        f"Armed with a {me['weapon']}; {me['combat']}." if me.get("weapon") else f"Unarmed; {me['combat']}.",
        f"{me['name']} is {condition(npc.get('health', 100), npc.get('alive', True))} and was "
        f"{ACTIVITY_WORDS.get((npc.get('controller') or {}).get('activity'), 'standing about')}.",
        f"The stranger (a traveller nobody here knows) is about {steps} steps away and "
        f"{condition(state['player'].get('health', 100), state['player'].get('alive', True))}"
        + (f", carrying: {', '.join(carried)}." if carried else ", empty-handed."),
        f"What {me['name']} knows, oldest first:"]
    for memory in my_mind["memories"]:
        source = {"witnessed": "saw", "victim": "it happened to them"}.get(memory["source"], memory["source"])
        doubted = " (they doubt this)" if memory.get("doubted") else ""
        lines.append(f"- ({source}) {memory['summary']}{doubted}")
    feelings = my_mind["feelings"]
    lines.append(f"Feelings toward the stranger: fear {feelings['fear']:.1f} of 1, anger {feelings['anger']:.1f} of 1.")
    others = [f"{n['name']} ({card(n)['role']}, {condition(n.get('health', 100), n.get('alive', True))}, "
              f"{round(math.dist(_cell(n), _cell(npc)))} steps)" for n in state["npcs"]
              if n["id"] != npc["id"] and math.dist(_cell(n), _cell(npc)) <= 16]
    if others:
        lines.append("People nearby: " + "; ".join(others) + ".")
    return "\n".join(lines)


def decision_request(state: dict, pending: dict) -> tuple[str, dict]:
    npc = find(state["npcs"], pending["npc_id"])
    name = npc["name"]
    if pending["kind"] == "resolve_attack":
        me = card(npc)
        text = (f"{name}, the {me['role']} ({me['combat']}), is attacking the stranger at close range "
                f"{'with a ' + me['weapon'] if me.get('weapon') else 'with bare hands'}. The stranger is "
                f"{condition(state['player'].get('health', 100))} and is not armoured.\n" + _situation(state, npc))
        return text, {"result": {"type": "choice", "instructions": f"What happens when {name} strikes at the stranger?",
                                 "criteria": {"missed": "The blow misses or is dodged.",
                                              "wounded": "The blow lands and wounds the stranger.",
                                              "killed": "The blow kills the stranger."}}}
    questions = {
        "action": {"type": "choice", "criteria": legal_actions(state, npc),
                   "instructions": f"Given who {name} is and what they know, what does {name} do right now?"},
        "fear": {"type": "score", "criteria": FEAR_LEVELS,
                 "instructions": f"How afraid of the stranger is {name} now?"},
        "anger": {"type": "score", "criteria": ANGER_LEVELS,
                  "instructions": f"How angry at the stranger is {name} now?"},
    }
    latest = mind(npc)["memories"][-1] if mind(npc)["memories"] else None
    if latest and latest["source"].startswith(("told_by", "heard")):
        questions["believes"] = {"type": "noul", "instructions": f"Does {name} believe what they just heard?"}
    return _situation(state, npc), questions


# --- Acting ----------------------------------------------------------------------------------

def _set_job(npc: dict, job: dict | None, now: int) -> None:
    mind(npc)["job"] = job
    controller = npc.get("controller")
    if controller is None:
        return
    if job is None:
        controller.update(source="routine", activity="look", path=[], next_at_ms=now + 1500, step_carry_ms=0)
    else:
        controller.update(source="job", path=[], step_carry_ms=0,
                          activity="walk" if job["kind"] in ("flee", "report", "approach", "attack") else "look")


def _flee_goal(state: dict, npc: dict, blocked: set) -> list[int]:
    _, steps = crafting._bfs(_cell(npc), blocked, 14)
    here = player_cell(state)
    goal = max(steps, key=lambda c: (math.dist(c, here), -steps[c]))
    return [goal[0], goal[1]]


def _shout_line(npc: dict) -> str:
    worst = max(mind(npc)["memories"], key=lambda m: m["severity"], default=None)
    if worst is None:
        return "Guards! Over here!"
    return {"violence": "Murder! Guards! Help!" if worst["severity"] >= 3 else "Help! Guards! He attacked us!",
            "theft": "Thief! Guards, stop that thief!"}.get(worst["kind"], "Guards! Over here!")


def apply_decision(state: dict, npc: dict, answers: dict, now: int, journal: list[dict]) -> dict:
    """Carry out one person's decision. Returns a short record for the trace and journal."""
    my_mind = mind(npc)
    levels = len(FEAR_LEVELS) - 1
    if "fear" in answers:
        my_mind["feelings"]["fear"] = round(float(answers["fear"]["score"]) / levels, 2)
    if "anger" in answers:
        my_mind["feelings"]["anger"] = round(float(answers["anger"]["score"]) / levels, 2)
    if "believes" in answers and answers["believes"]["noul"] < 0.5 and my_mind["memories"]:
        my_mind["memories"][-1]["doubted"] = True
    options = legal_actions(state, npc)
    choice = answers.get("action", {}).get("choice")
    if choice not in options:
        choice = "watch"
    blocked = crafting._blocked_cells(state)
    kind, _, target = choice.partition(":")
    if kind == "carry_on":
        _set_job(npc, None, now)
    elif kind == "watch":
        _set_job(npc, {"kind": "watch", "until": now + 20_000}, now)
    elif kind == "flee":
        _say(npc, "Stay away from me!", now, state, journal)
        _set_job(npc, {"kind": "flee", "goal": _flee_goal(state, npc, blocked), "speed": "run",
                       "until": now + 40_000}, now)
    elif kind == "shout_for_help":
        line = _shout_line(npc)
        _say(npc, line, now, state, journal)
        worst = max(my_mind["memories"], key=lambda m: m["severity"], default=None)
        for other in state["npcs"]:
            if other["id"] == npc["id"] or not other.get("alive", True):
                continue
            if math.dist(_cell(other), _cell(npc)) <= HEAR_SHOUT_CELLS:
                heard = f"{npc['name']} shouted “{line}”"
                memory = {"kind": worst["kind"] if worst else "alarm", "severity": worst["severity"] if worst else 1,
                          "summary": heard + (f" — {npc['name']} says: {worst['summary']}" if worst else "."),
                          "short": worst["short"] if worst else "caused trouble",
                          "victim": worst["victim"] if worst else None, "at": now, "source": f"heard:{npc['id']}"}
                mind(other)["memories"] = (mind(other)["memories"] + [memory])[-MEMORY_LIMIT:]
                add_pending(state, other["id"], "decide", "heard a shout")
        _set_job(npc, {"kind": "watch", "until": now + 20_000}, now)
    elif kind == "report":
        _set_job(npc, {"kind": "report", "target": target, "speed": "run"}, now)
    elif kind == "confront":
        my_mind["confronted_at"] = now
        _set_job(npc, {"kind": "approach", "target": "player", "stop": 2.0, "speed": "walk", "then": "confront"}, now)
    elif kind == "attack":
        _say(npc, "Stop right there!" if card(npc).get("guard") else "You'll pay for that!", now, state, journal)
        _set_job(npc, {"kind": "attack", "target": "player", "speed": "run", "next_at": now}, now)
    elif kind == "help":
        _set_job(npc, {"kind": "approach", "target": target, "stop": 1.5, "speed": "walk", "then": "help"}, now)
    return {"npc_id": npc["id"], "action": choice, "feelings": dict(my_mind["feelings"])}


def resolve_attack(state: dict, npc: dict, answers: dict, seed: str, journal: list[dict]) -> dict:
    """An NPC's blow against the player. Sample the decider's distribution so fights aren't scripted."""
    player = state["player"]
    probabilities = answers.get("result", {}).get("probabilities") or {"wounded": 1.0}
    rng = random.Random(seed)
    outcomes = [k for k in ("missed", "wounded", "killed") if probabilities.get(k, 0) > 0] or ["wounded"]
    result = rng.choices(outcomes, weights=[probabilities.get(k, 0) for k in outcomes])[0]
    health = player.get("health", 100)
    if result == "killed":
        health = 0
    elif result == "wounded":
        health = max(0, health - PLAYER_WOUND)
        result = "killed" if health == 0 else result
    player.update(health=health, alive=health > 0)
    weapon = card(npc).get("weapon") or "fists"
    text = {"missed": f"{npc['name']} swings the {weapon} at you and misses.",
            "wounded": f"{npc['name']} strikes you with the {weapon}. You are wounded.",
            "killed": f"{npc['name']} strikes you down with the {weapon}."}[result]
    if result != "missed":
        player.setdefault("injuries", []).append(f"struck by {npc['name']}'s {weapon}")
    journal.append({"kind": "npc_attack", "npc_id": npc["id"], "result": result, "category": "attacked",
                    "reason": text})
    if not player["alive"]:
        for other in state["npcs"]:
            job = (other.get("mind") or {}).get("job")
            if job and job.get("target") == "player":
                _set_job(other, {"kind": "watch", "until": state["sim_time_ms"] + 20_000}, state["sim_time_ms"])
    return {"npc_id": npc["id"], "action": "strike", "result": result, "probabilities": probabilities}


# --- Time passing ------------------------------------------------------------------------------

def _target_cell(state: dict, npcs: list[dict], job: dict) -> tuple[int, int] | None:
    if "goal" in job:
        return tuple(job["goal"])
    if job.get("target") == "player":
        return player_cell(state) if state["player"].get("alive", True) else None
    target = find(npcs, job.get("target") or "")
    return _cell(target) if target and target.get("alive", True) else None


def _next_step(start: tuple[int, int], goal: tuple[int, int], stop: float, blocked: set) -> tuple[int, int] | None:
    previous, steps = crafting._bfs(start, blocked, 60)
    goals = [c for c in steps if math.dist(c, goal) <= stop]
    if not goals:
        return None
    cell = min(goals, key=lambda c: (steps[c], math.dist(c, goal)))
    while previous.get(cell) not in (start, None):
        cell = previous[cell]
    return None if cell == start else cell


def _deliver_report(state: dict, npcs: list[dict], npc: dict, target: dict, now: int, journal: list[dict]) -> None:
    worst = max(mind(npc)["memories"], key=lambda m: m["severity"], default=None)
    if worst is None:
        return
    line = f"{target['name']}! The stranger {worst['short']}!"
    _say(npc, line, now, state, journal)
    memory = {**{k: worst[k] for k in ("kind", "severity", "short", "victim")},
              "summary": f"{npc['name']} told them: {worst['summary']}", "at": now, "source": f"told_by:{npc['id']}"}
    mind(target)["memories"] = (mind(target)["memories"] + [memory])[-MEMORY_LIMIT:]
    add_pending(state, target["id"], "decide", f"told by {npc['name']}")


def advance_world(state: dict, elapsed_ms: int, now: int) -> tuple[list[dict], list[dict]]:
    """People follow routines or their current job for elapsed_ms. Returns (npcs, journal lines).

    May queue thinking in state["pending_minds"] (someone told, an attacker in reach).
    """
    npcs = npc_sim.advance_npcs(state["npcs"], elapsed_ms, now, crafting.m2._GEOMETRY)
    working = copy.copy(state)
    working["npcs"] = npcs
    journal: list[dict] = []
    blocked = crafting._blocked_cells(state)
    end = now + elapsed_ms
    for npc in npcs:
        job = (npc.get("mind") or {}).get("job")
        if not job or not npc.get("alive", True):
            continue
        if job["kind"] == "watch":
            if end >= job["until"]:
                _set_job(npc, None, end)
            continue
        goal = _target_cell(working, npcs, job)
        if goal is None or (job["kind"] == "attack" and math.dist(_cell(npc), goal) > GIVE_UP_CELLS):
            _set_job(npc, None, end)
            continue
        stop = {"flee": 0.0, "report": 1.5, "attack": 1.5}.get(job["kind"], job.get("stop", 1.5))
        controller = npc.get("controller") or {}
        carry = controller.get("step_carry_ms", 0) + elapsed_ms
        step_ms = RUN_STEP_MS if job.get("speed") == "run" else WALK_STEP_MS
        while carry >= step_ms and math.dist(_cell(npc), goal) > stop:
            carry -= step_ms
            step = _next_step(_cell(npc), goal, stop, blocked)
            if step is None:
                break
            npc["x"], npc["y"] = step
        controller["step_carry_ms"] = carry if math.dist(_cell(npc), goal) > stop else 0
        if math.dist(_cell(npc), goal) > stop:
            continue
        # Arrived.
        if job["kind"] == "flee":
            _set_job(npc, {"kind": "watch", "until": end + 20_000}, end)
        elif job["kind"] == "report":
            target = find(npcs, job["target"])
            if target:
                _deliver_report(working, npcs, npc, target, end, journal)
            _set_job(npc, {"kind": "watch", "until": end + 15_000}, end)
        elif job["kind"] == "approach" and job.get("then") == "confront":
            _say(npc, "What do you think you're doing?!", end, working, journal)
            _set_job(npc, {"kind": "watch", "until": end + 15_000}, end)
            add_pending(working, npc["id"], "decide", "confronted the stranger")
        elif job["kind"] == "approach":
            _set_job(npc, {"kind": "watch", "until": end + 20_000}, end)
            controller["activity"] = "work"
        elif job["kind"] == "attack" and end >= job.get("next_at", 0):
            add_pending(working, npc["id"], "resolve_attack", "in reach")
            job["next_at"] = end + ATTACK_INTERVAL_MS
    state["pending_minds"] = working.get("pending_minds", state.get("pending_minds", []))
    return npcs, journal
