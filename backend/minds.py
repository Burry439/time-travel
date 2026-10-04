"""NPC decisions and their execution. Private perception queues each person's model request;
models choose motives, speech, goals and physical intentions. The backend validates authority,
resources and commitments and advances jobs. Physical work uses the shared judge and reducer."""

from __future__ import annotations

import math

import actors
import agreements
import cast
import combat
import paths
import persona
import reputation
import speech
import tuning
from shapes import Npc, State

ACTIVITY_WORDS = {
    "work": "working",
    "look": "keeping watch",
    "patrol": "patrolling",
    "wait": "waiting",
    "walk": "walking",
    "conversation": "talking",
    "dead": "lying dead",
}


# --- Small helpers ---------------------------------------------------------------------------


# --- Perception --------------------------------------------------------------------------------


# --- Options, lines and deciding ---------------------------------------------------------------


def options_for(state: State, npc: Npc) -> dict[str, dict]:
    """Every option code can carry out for this person right now: action, target, line, description."""
    name, me = npc["name"], cast.card(npc)
    armed = cast.armed_with(state, npc)
    worst = reputation.worst_memory(npc)
    victim = cast.find(state["npcs"], (worst or {}).get("victim") or "")
    slots_ = speech.slots(state, npc)
    bases: list[tuple[str, str, str | None, str | None]] = [  # (key, description, action for lines, target)
        ("carry_on", f"{name} ignores it and carries on with what they were doing.", None, None),
        ("watch", f"{name} stays where they are and keeps a wary eye on the stranger.", None, None),
        ("flee", f"{name} runs away from the stranger to somewhere safe.", "flee", None),
    ]
    if not me.get("guard"):
        bases.append(("hide", f"{name} slips away out of the stranger's sight and stays hidden.", None, None))
        bases.append(
            ("warn_others", f"{name} calls out to warn people nearby about the stranger.", "warn_others", None)
        )
    if not (worst is not None and worst.get("event") in cast.mind(npc).get("shouted", [])):
        bases.append(
            (
                "shout_for_help",
                f"{name} shouts loudly for help and for the guards, right where they are.",
                "shout_for_help",
                None,
            )
        )
    if me.get("guard"):
        bases.append(("whistle", f"{name} blows a whistle to call every guard within earshot.", "whistle", None))
    if state["player"].get("alive", True):
        recently = (cast.mind(npc).get("confronted_at") or -(10**9)) > state["sim_time_ms"] - 60_000
        if not recently:
            bases.append(("confront", f"{name} walks up to the stranger and demands an explanation.", "confront", None))
            if armed:
                bases.append(
                    (
                        "threaten",
                        f"{name} walks up to the stranger brandishing their {armed}, "
                        "warning them off without striking yet.",
                        "threaten",
                        None,
                    )
                )
            if worst and worst["kind"] == "theft" and worst.get("victim") == npc["id"]:
                bases.append(
                    (
                        "demand_payment",
                        f"{name} goes to the stranger and demands their {slots_['item']} back or payment for it.",
                        "demand_payment",
                        None,
                    )
                )
        weapon = f" with their {armed}" if armed else " with bare hands"
        bases.append(
            ("attack", f"{name} attacks the stranger{weapon} ({me.get('combat', 'no fighter')}).", "attack", None)
        )
    told = sorted(
        (g for g in state["npcs"] if g["id"] != npc["id"] and g.get("alive", True) and cast.card(g).get("guard")),
        key=lambda g: cast.distance(g, npc),
    )[:2]
    told += [
        cast.find(state["npcs"], f)
        for f in cast.card(npc).get("family", [])
        if cast.find(state["npcs"], f)
        and cast.find(state["npcs"], f).get("alive", True)
        and cast.find(state["npcs"], f) not in told
    ]
    for person in told:
        steps = round(cast.distance(person, npc))
        who = cast.relation(npc, person["id"]) or f"{person['name']} the {cast.card(person)['role']}"
        bases.append(
            (
                f"report:{person['id']}",
                f"{name} goes to {who} (about {steps} steps away) and tells them what happened.",
                "report",
                person["name"],
            )
        )
    if victim and victim["id"] != npc["id"] and victim.get("alive", True) and victim.get("health", 100) < 100:
        bases.append((f"help:{victim['id']}", f"{name} goes to help {victim['name']}, who is hurt.", "help", None))
    options: dict[str, dict] = {}
    for key, description, line_action, spoken_to in bases:
        action, _, target = key.partition(":")
        record = {"action": action, "target": target or None, "line": None, "line_id": None}
        choices = (
            speech.choose_lines(state, npc, line_action, {**slots_, "guard": spoken_to or slots_["guard"]})
            if line_action
            else []
        )
        if not choices:
            options[key] = {**record, "description": description}
            continue
        for line_id, text in choices:
            options[f"{key}|{line_id}"] = {
                **record,
                "line": text,
                "line_id": line_id,
                "description": f"{description} Says: “{text}”",
            }
    return options


def legal_actions(state: State, npc: Npc) -> dict[str, str]:
    return {key: option["description"] for key, option in options_for(state, npc).items()}


def situation(state: State, npc: Npc) -> str:
    me, my_mind = cast.card(npc), cast.mind(npc)
    here = cast.player_cell(state)
    known_as = persona.knows(npc).get("name") or persona.knows(npc).get("heard_name")
    steps = round(cast.distance(npc, here))
    carried = [o["name"] for o in state["objects"].values() if o["holder_id"] == "player"]
    lines = [
        f"{me['name']} is the {me['role']} ({me.get('age', '?')}) in a small premodern town outside a walled city. "
        f"{me['personality']}",
        f"Values: {me['values']}. Fears: {me['fears']}.",
        f"Authority: {me['authority']}",
        f"Armed with a {armed}; {me['combat']}."
        if (armed := cast.armed_with(state, npc))
        else f"Unarmed; {me['combat']}.",
        *persona.sheet_lines(state, npc),
        f"{me['name']} is {cast.condition(npc.get('health', 100), npc.get('alive', True))} and was "
        f"{ACTIVITY_WORDS.get((npc.get('controller') or {}).get('activity'), 'standing about')}.",
        (
            f"The stranger ({known_as}, a traveller new to these parts)"
            if known_as
            else "The stranger (a traveller nobody here knows)"
        )
        + f" is about {steps} steps away and "
        f"{cast.condition(state['player'].get('health', 100), state['player'].get('alive', True))}"
        + (f", carrying: {', '.join(carried)}." if carried else ", empty-handed."),
    ]
    remembered = persona.stranger_lines(state, npc)
    if remembered:
        lines.append(f"What {me['name']} remembers of the stranger:")
        lines += [f"- {line}" for line in remembered]
    lines.append(f"What {me['name']} knows, oldest first:")
    for memory in my_mind["memories"]:
        source = {
            "witnessed": "saw from nearby" if memory.get("clarity") != "vague" else "saw from a distance",
            "victim": "it happened to them",
            "received": "it was given to them",
            "shown": "was shown it up close",
        }.get(memory["source"], memory["source"])
        kind, _, teller = memory["source"].partition(":")
        if kind in ("told_by", "heard") and cast.find(state["npcs"], teller):
            name = cast.find(state["npcs"], teller)["name"]
            source = ("told by " if kind == "told_by" else "heard ") + (cast.relation(npc, teller) or name)
        doubted = " (they doubt this)" if memory.get("doubted") else ""
        who = cast.relation(npc, memory.get("victim"))
        lines.append(f"- ({source}) {memory['summary']}{doubted}" + (f" [{who}]" if who else ""))
    for deal in sorted(
        (
            a
            for a in state.get("agreements", {}).values()
            if a.get("issuer") == npc["id"] and a.get("status") in ("proposed", "accepted", "fulfilled")
        ),
        key=lambda a: a["id"],
    ):
        status = {"proposed": "offered, not yet agreed", "accepted": "agreed, not yet done", "fulfilled": "done"}[
            deal["status"]
        ]
        lines.append(f"{me['name']}'s deal with the stranger ({status}): the stranger is to {deal['task']}.")
    feelings, view = my_mind["feelings"], reputation.regard(npc)
    lines.append(
        f"How {me['name']} feels about the stranger right now: "
        f"{reputation.in_words(feelings['fear'], reputation.FEAR_LEVELS).lower()}, {reputation.in_words(feelings['anger'], reputation.ANGER_LEVELS).lower()}; "
        f"trust {reputation.in_words(view['trust'], ['none', 'little', 'some', 'real'])}, "
        f"suspicion {reputation.in_words(view['suspicion'], ['none', 'slight', 'wary', 'very wary'])}, "
        f"respect for what they can do {reputation.in_words(view['respect'], ['none', 'a little', 'real', 'great'])}, "
        f"awe {reputation.in_words(view['awe'], ['none', 'a touch', 'deep', 'overwhelming'])}."
    )
    others = [
        f"{n['name']} ({cast.relation(npc, n['id']) or cast.card(n)['role']}, "
        f"{cast.condition(n.get('health', 100), n.get('alive', True))}, {round(cast.distance(n, npc))} steps)"
        for n in state["npcs"]
        if n["id"] != npc["id"] and cast.distance(n, npc) <= 16
    ]
    if others:
        lines.append("People nearby: " + "; ".join(others) + ".")
    return "\n".join(lines)


def questions(state: State, npc: Npc, prefix: str = "") -> dict:
    name = npc["name"]
    questions = {
        f"{prefix}action": {
            "type": "choice",
            "criteria": legal_actions(state, npc),
            "instructions": f"Given who {name} is and what they know, what does {name} do and say right now?",
        },
        f"{prefix}fear": {
            "type": "score",
            "criteria": reputation.FEAR_LEVELS,
            "instructions": f"How afraid of the stranger is {name} now?",
        },
        f"{prefix}anger": {
            "type": "score",
            "criteria": reputation.ANGER_LEVELS,
            "instructions": f"How angry at the stranger is {name} now?",
        },
    }
    latest = cast.mind(npc)["memories"][-1] if cast.mind(npc)["memories"] else None
    if latest and latest["source"].startswith(("told_by", "heard")):
        questions[f"{prefix}believes"] = {"type": "noul", "instructions": f"Does {name} believe what they just heard?"}
    return questions


# --- Acting ----------------------------------------------------------------------------------


def away_goal(state: State, npc: Npc, blocked: paths.Grid, hidden: bool = False) -> list[int]:
    """A reachable cell far from the stranger; for hiding, one the stranger can't see."""
    _, steps = paths.bfs(cast.cell(npc), blocked, 14)
    here = cast.player_cell(state)
    cells = [c for c in steps if not hidden or not paths.line_of_sight(state, c, here)] or list(steps)
    goal = max(cells, key=lambda c: (math.dist(c, here), -steps[c]))
    return [goal[0], goal[1]]


def raise_alarm(state: State, npc: Npc, line: str, radius: float, now: int, guards_only: bool = False) -> None:
    """Everyone within earshot who didn't already know hears about it and may react."""
    worst = reputation.worst_memory(npc)
    if worst is not None:
        cast.mind(npc).setdefault("shouted", []).append(worst.get("event"))
    for other in state["npcs"]:
        if (
            other["id"] == npc["id"]
            or not other.get("alive", True)
            or (guards_only and not cast.card(other).get("guard"))
        ):
            continue
        if worst is not None and reputation.knows(other, worst):
            continue  # Old news to them.
        if cast.distance(other, npc) > radius:
            continue
        heard = f"{npc['name']} called out “{line}”"
        memory = {
            **(
                {k: worst[k] for k in ("evidence_id", "object_id", "actor_id", "revision", "application") if k in worst}
                if worst
                else {}
            ),
            "kind": worst["kind"] if worst else "alarm",
            "severity": worst["severity"] if worst else 1,
            "event": worst.get("event") if worst else None,
            "clarity": "heard",
            "summary": heard + (f" — {npc['name']} says: {worst['summary']}" if worst else "."),
            "short": worst["short"] if worst else "caused trouble",
            "item": (worst or {}).get("item"),
            "victim": worst["victim"] if worst else None,
            "at": now,
            "source": f"heard:{npc['id']}",
        }
        reputation.remember(other, memory)
        cast.mind(other)["rethinks"] = 0
        cast.add_pending(state, other["id"], "decide", f"heard {npc['name']}")
        if cast.card(other).get("guard"):
            for known in cast.mind(npc)["memories"]:
                known["reported"] = True  # A guard heard: the caller has done their part.


def apply_personal_decision(state, npc, decision, now, journal):
    """One contract for subjective judgments and resource-checked intentions in every lane."""
    import talk

    talk.update_regard(npc, decision["answers"])
    cast.mind(npc)["feelings"]["anger"] = float(decision["answers"]["anger"]["score"]) / 3
    cast.mind(npc)["standing_plan"] = {"defend": bool(decision.get("defend_if_attacked"))}
    rejected = []
    for intent in decision.get("intents", []):
        if not agreements.execute(state, npc, intent, state["event_seq"] + 1):
            rejected.append("The intended action is unavailable with the resources here.")
    if decision.get("agreement"):
        valid, detail = agreements.apply(state, npc, decision["agreement"], state["event_seq"] + 1)
        if not valid:
            rejected.append(detail)
    if decision.get("text"):
        speech.say(
            npc,
            decision["text"] if not rejected else "I can't carry that out with what I have here.",
            now,
            state,
            journal,
        )
    cast.mind(npc)["decision_reason"] = decision.get("remember", "")[:400]
    if rejected:
        cast.mind(npc)["rejected_intents"] = rejected
    return rejected


def apply_decision(state: State, npc: Npc, answers: dict, now: int, journal: list[dict]) -> dict:
    """Carry out one person's decision (action and line). Returns a short record for the trace."""
    if answers.get("actor_physical"):
        result = actors.perform(state, npc["id"], answers["actor_physical"])
        return {"npc_id": npc["id"], "action": "physical", "category": result["category"]}
    decision = answers.get("npc_decision")
    if decision:
        apply_personal_decision(state, npc, decision, now, journal)
        answers = {"action": {"choice": decision["move"]}, "believes": decision["answers"]["believes"]}
    my_mind = cast.mind(npc)
    levels = len(reputation.FEAR_LEVELS) - 1
    stirred = my_mind.get("stirred") or {}
    for feeling in ("fear", "anger"):  # Feelings rise at once, hold for the moment, then cool one step at a time.
        if feeling in answers:
            now_felt = float(answers[feeling]["score"]) / levels
            before = my_mind["feelings"].get(feeling, 0.0)
            floor = stirred.get(feeling, 0.0) if now < stirred.get("until", 0) else before - 1 / levels
            my_mind["feelings"][feeling] = round(max(now_felt, floor), 2)
    if "believes" in answers and answers["believes"]["noul"] < 0.5 and my_mind["memories"]:
        my_mind["memories"][-1]["doubted"] = True
    options = options_for(state, npc)
    choice = answers.get("action", {}).get("choice")
    if choice not in options:  # e.g. the answer named the action without a line: take its first line.
        base = (choice or "").split("|")[0]
        choice = next((key for key in options if key.split("|")[0] == base), None) or next(
            key for key in options if key.startswith("watch")
        )
    option = options[choice]
    action, target, line, line_id = option["action"], option["target"], option["line"], option["line_id"]
    blocked = paths.grid(state)
    # Carrying on, for someone on an errand, is carrying on with it (D-54; D-63: a reconsideration right after Darin
    # agreed to go and pay Hessa sent him back to his stall). Any other choice may still replace the errand.
    on_errand = (my_mind.get("job") or {}).get("kind") in cast.ERRAND_JOBS
    if action == "carry_on":
        if not on_errand:
            cast.set_job(npc, None, now)
    elif action == "watch":
        if not on_errand:
            cast.watch(npc, now, tuning.WATCH_MS)
    elif action in ("flee", "hide"):
        if line:
            speech.say(npc, line, now, state, journal, line_id)
        cast.set_job(
            npc,
            {
                "kind": "flee",
                "goal": away_goal(state, npc, blocked, hidden=action == "hide"),
                "speed": "run",
                "until": now + 40_000,
            },
            now,
        )
    elif action in ("shout_for_help", "warn_others", "whistle"):
        speech.say(npc, line or "Guards!", now, state, journal, line_id)
        radius = {
            "shout_for_help": tuning.HEAR_SHOUT_CELLS,
            "warn_others": tuning.WARN_CELLS,
            "whistle": tuning.WHISTLE_CELLS,
        }[action]
        raise_alarm(state, npc, line or "Guards!", radius, now, guards_only=action == "whistle")
        cast.watch(npc, now, tuning.WATCH_MS)
    elif action == "report":
        guard = cast.find(state["npcs"], target)
        if guard:
            speech.say(
                npc, f"I'm fetching {guard['name']}!", now, state, journal
            )  # Seen setting off, not just arriving.
        cast.set_job(npc, {"kind": "report", "target": target, "speed": "run", "line": line, "line_id": line_id}, now)
    elif action in ("confront", "threaten", "demand_payment"):
        my_mind["confronted_at"] = now
        if cast.distance(npc, state["player"]) > 3:  # Called out now; the full line when they get there.
            calls = speech.LINES.get("call_out", {}).get("any") or ["Hey! You!"]
            speech.say(npc, calls[now // 1000 % len(calls)], now, state, journal)
        cast.set_job(
            npc,
            {
                "kind": "approach",
                "target": "player",
                "stop": 2.5 if action == "threaten" else 2.0,
                "speed": "walk",
                "then": action,
                "line": line,
                "line_id": line_id,
            },
            now,
        )
    elif action == "attack":  # A real-time fight: they come at the stranger with whatever they carry (D-41).
        if line:
            speech.say(npc, line, now, state, journal, line_id)
        combat.start(state, [npc["id"]], now, "decided")
    elif action == "help":
        cast.set_job(
            npc,
            {
                "kind": "approach",
                "target": target,
                "stop": 1.5,
                "speed": "walk",
                "then": "help",
                "line": line,
                "line_id": line_id,
            },
            now,
        )
    return {"npc_id": npc["id"], "action": choice, "feelings": dict(my_mind["feelings"])}


# --- Time passing ------------------------------------------------------------------------------
