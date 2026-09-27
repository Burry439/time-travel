"""NPC minds: perception, memories, feelings, decisions and the actions that follow.

Code decides who could perceive an event (and how clearly), which actions are legal for each
person, what those actions do over time, and how fights go. The decider role (Jev) is asked only
at decision points: it chooses among the legal options - each paired with lines in that person's
voice - and rates feelings. Everyone deciding at the same moment shares one Jev request.

Flow: a committed player act -> perceive() gives witnesses memories and queues them in
state["pending_minds"] -> the client's thinking lane calls /think -> batch_request() -> Jev ->
apply_decision() starts jobs (flee, hide, shout, warn, whistle, report, confront, threaten,
demand payment, attack, help) -> advance_world() moves people along their jobs each clock beat
and applies calm ambient rules. Anyone who reaches the stranger to address them (a halt, a
confrontation, an attack) opens or joins an encounter (encounter.py), where everything happens
in simultaneous rounds; blows are a seeded roll there, never on the clock.
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
_CARD_FILE = json.loads((ROOT / "data" / "content" / "npc_cards.json").read_text(encoding="utf-8"))
CARDS: dict[str, dict] = _CARD_FILE["npcs"]
WEAPONS: dict[str, dict] = _CARD_FILE["weapons"]
_LINE_FILE = json.loads((ROOT / "data" / "content" / "lines.json").read_text(encoding="utf-8"))
LINES: dict[str, dict] = _LINE_FILE["lines"]
CUES: dict[str, list[str]] = _LINE_FILE["cues"]
TRUST_BANDS = (0.3, 0.45, 0.6, 0.75)  # Crossing one of these shows as a small in-character cue.
SUSPICION_BANDS = (0.4, 0.6, 0.8)
GEOMETRY = json.loads((ROOT / "data" / "world_geometry.json").read_text(encoding="utf-8"))
WALLS = {(cx, cy) for b in GEOMETRY["buildings"] for x, y, w, h in [b["cells"]]
         for cx in range(x, x + w) for cy in range(y, y + h)}  # Buildings block sight; trees do not.
SIGHT_CELLS = 10.0
CLEAR_VIEW_CELLS = 5.0  # Closer than this, a witness sees exactly what happened; further, only a scuffle.
HEAR_SHOUT_CELLS = 30.0  # A shout for help carries across the open road.
WARN_CELLS = 12.0
WHISTLE_CELLS = 45.0
AMBIENT_CELLS = 8.0  # Wary people turn to face the stranger within this range.
MAX_RETHINKS = 2  # Automatic reconsiderations per person after their latest memory.
MEMORY_LIMIT = 12
RUN_STEP_MS = 170
WALK_STEP_MS = 400
ATTACK_INTERVAL_MS = 2500
GIVE_UP_CELLS = 28.0
GATE_ZONE = (38, 58, 17)  # x from, x to, rows up to: the gate approach, where guards stop strangers.
HALT_EVERY_MS = 180_000  # A stranger who was stopped isn't stopped again for a while.
HALT_REACH_CELLS = 14.0
THINK_BATCH = 6  # People who can think in one /think call (one Jev request); the rest wait for the next.
ACTIVITY_WORDS = {"work": "working", "look": "keeping watch", "patrol": "patrolling", "wait": "waiting",
                  "walk": "walking", "conversation": "talking", "dead": "lying dead"}
FEAR_LEVELS = ["Not afraid", "Uneasy", "Afraid", "Terrified"]
ANGER_LEVELS = ["Calm", "Annoyed", "Angry", "Furious"]
FAMILY_WORDS = ("sister", "brother", "nephew", "aunt")
EVIDENCE_KINDS = ("demonstration", "vouch", "help", "gift")  # Good things seen or heard about the stranger.
CRIME_KINDS = ("violence", "theft")
EVIDENCE_SHIFT = 0.15  # Regard change for one clear piece of evidence (or, doubled, one crime).


# --- Small helpers ---------------------------------------------------------------------------

def card(npc: dict) -> dict:
    return CARDS.get(npc["id"], {"name": npc["name"], "role": npc["role"], "guard": False, "weapon": None,
                                 "combat": "no fighter", "personality": "", "values": "", "fears": "",
                                 "authority": "", "skill": 0, "tones": ["frightened"], "relations": {},
                                 "family": []})


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


def knows(npc: dict, event) -> bool:
    """Already has a memory of this event (so news about it is not new)."""
    return event is not None and any(m.get("event") == event for m in mind(npc)["memories"])


def worst_memory(npc: dict) -> dict | None:
    return max(mind(npc)["memories"], key=lambda m: m["severity"], default=None)


def relation(npc: dict, other_id: str | None) -> str | None:
    """How this person refers to someone they know, e.g. 'her nephew Jory'."""
    return card(npc).get("relations", {}).get(other_id or "")


def is_family(npc: dict, other_id: str | None) -> bool:
    return (other_id or "") in card(npc).get("family", [])


def regard(npc: dict) -> dict:
    """How this person sees the stranger (GDD 7.2): starts from their card, changes only through events."""
    start = card(npc).get("regard", {"trust": 0.2, "suspicion": 0.5})
    return mind(npc).setdefault("regard", {"trust": start["trust"], "suspicion": start["suspicion"],
                                           "goodwill_used": 0.0})


def is_evidence(memory: dict) -> bool:
    """Seen clearly (or told by someone), and it worked: something real in the stranger's favour."""
    return memory["kind"] in EVIDENCE_KINDS and memory.get("clarity") != "vague" and memory.get("works", True)


def regard_cue(npc: dict, before: dict, after: dict) -> None:
    """A small sign the player can read when someone's view of them crosses a band. Never numbers."""
    def band(value: float, bands: tuple) -> int:
        return sum(value >= b for b in bands)
    trust = band(after["trust"], TRUST_BANDS) - band(before["trust"], TRUST_BANDS)
    suspicion = band(after["suspicion"], SUSPICION_BANDS) - band(before["suspicion"], SUSPICION_BANDS)
    if trust > 0:
        kind = "trusting" if after["trust"] >= TRUST_BANDS[-1] else "warmer"
    elif trust < 0:
        kind = "cooler"
    elif suspicion > 0:
        kind = "wary"
    elif suspicion < 0:
        kind = "easier"
    else:
        return
    count = mind(npc).get("cue_count", 0) + 1
    pool = CUES[kind]
    mind(npc).update(cue_count=count, cue={"kind": kind, "key": f"{npc['id']}:cue:{count}",
                                           "text": pool[(count + len(npc["id"])) % len(pool)].format(name=npc["name"])})


def _shift_regard(npc: dict, memory: dict) -> None:
    """Evidence raises trust and eases suspicion; a crime does the opposite. Once per event."""
    view = regard(npc)
    credited = view.setdefault("credited", [])
    if memory.get("event") is not None and memory.get("event") in credited:
        return
    if is_evidence(memory):
        trust, suspicion = EVIDENCE_SHIFT, -EVIDENCE_SHIFT
    elif memory["kind"] in CRIME_KINDS and memory.get("clarity") != "vague":
        trust, suspicion = -2 * EVIDENCE_SHIFT, 2 * EVIDENCE_SHIFT
    elif memory["kind"] == "arrest":
        trust, suspicion = -EVIDENCE_SHIFT, EVIDENCE_SHIFT
    else:
        return
    if memory.get("event") is not None:
        credited.append(memory["event"])
    before = dict(view)
    view["trust"] = round(min(1.0, max(0.0, view["trust"] + trust)), 3)
    view["suspicion"] = round(min(1.0, max(0.0, view["suspicion"] + suspicion)), 3)
    regard_cue(npc, before, view)


def remember(npc: dict, memory: dict) -> None:
    """Add a memory (evidence and crimes move regard); past the limit, forget the least serious one."""
    _shift_regard(npc, memory)
    memories = mind(npc)["memories"]
    memories.append(memory)
    while len(memories) > MEMORY_LIMIT:
        memories.remove(min(memories[:-1], key=lambda m: m.get("severity", 0)))


def add_pending(state: dict, npc_id: str, kind: str = "decide", why: str = "") -> None:
    pending = state.setdefault("pending_minds", [])
    if not any(p["npc_id"] == npc_id and p["kind"] == kind for p in pending):
        pending.append({"npc_id": npc_id, "kind": kind, "why": why})


def calm(state: dict) -> bool:
    """No one is reacting to the player: a safe point to rewind to."""
    if state.get("pending_minds") or not state["player"].get("alive", True):
        return False
    if state.get("encounter") and state["encounter"].get("reason") != "talk":
        return False
    return not any((npc.get("mind") or {}).get("job") and npc["mind"]["job"]["kind"] in
                   ("attack", "report", "flee", "approach") for npc in state["npcs"])


def _say(npc: dict, text: str, now: int, state: dict, journal: list[dict], line_id: str | None = None,
         category: str = "heard") -> None:
    mind(npc)["said"] = {"text": text, "at": now, "key": f"{npc['id']}:{now}:{len(journal)}"}
    if line_id:
        mind(npc)["last_line"] = line_id
    if math.dist(_cell(npc), player_cell(state)) <= HEAR_SHOUT_CELLS:
        journal.append({"kind": "npc", "npc_id": npc["id"], "category": category,
                        "reason": f"{npc['name']}: “{text}”"})


# --- Perception --------------------------------------------------------------------------------

def _describe(state: dict, entry: dict) -> list[dict]:
    """What onlookers could see of a committed attempt, clearly and from afar: one view per notable thing.

    Violence and theft make people think about what to do; seeing something shown or given is only
    remembered (it counts as evidence about the stranger when they next talk).
    """
    names = {n["id"]: n["name"] for n in state["npcs"]}
    if entry.get("category") not in ("success", "partial_success"):
        return []
    views = []
    harm = entry.get("harm")
    if isinstance(harm, dict):
        victim = names.get(harm["target_id"], "someone")
        weapon = state["objects"].get(harm.get("weapon_id") or "", {}).get("name")
        how = f" with a {weapon}" if weapon else " with bare hands"
        verb = "threw a " + weapon + " at" if harm.get("method") == "thrown" and weapon else "attacked"
        outcome = {"killed": f"{victim} fell and did not get up.", "wounded": f"{victim} was hurt.",
                   "missed": f"The blow missed {victim}."}[harm["result"]]
        short = {"killed": f"killed {victim}", "wounded": f"attacked {victim}",
                 "missed": f"attacked {victim}"}[harm["result"]]
        severity = {"killed": 3, "wounded": 2, "missed": 1}[harm["result"]]
        views.append({"kind": "violence", "victim": harm["target_id"],
                      "clear": {"summary": f"The stranger {verb} {victim}{'' if 'threw' in verb else how}. {outcome}",
                                "short": short, "severity": severity},
                      "vague": {"summary": (f"There was a scuffle near the stranger and {victim} went down."
                                            if harm["result"] == "killed" else
                                            f"There was a scuffle near the stranger; {victim} cried out."),
                                "short": f"was in a fight with {victim}", "severity": max(1, severity - 1)}})
    claims = entry.get("property") or []
    if claims and not isinstance(harm, dict):  # A weapon grabbed for an attack is part of the attack.
        claim = claims[0]
        owner = names.get(claim["owner_id"], "someone")
        verb = {"taken": "took", "used up": "used up", "used": "used", "given away": "gave away"}.get(
            claim["how"], f"{claim['how']}")
        views.append({"kind": "theft", "victim": claim["owner_id"], "item": claim["name"],
                      "clear": {"summary": f"The stranger {verb} {owner}'s {claim['name']} without asking.",
                                "short": f"stole {owner}'s {claim['name']}", "severity": 1},
                      "vague": {"summary": f"The stranger was handling {owner}'s things.",
                                "short": f"was handling {owner}'s things", "severity": 1}})
    shown = entry.get("demonstration")
    if isinstance(shown, dict):
        views.append({"kind": "demonstration", "victim": None, "item": shown["object_name"],
                      "audience": shown.get("audience_ids", []), "think": False, "works": shown["works"],
                      "clear": {"summary": shown["observed"], "short": f"showed off a {shown['object_name']}",
                                "severity": 1},
                      "vague": {"summary": "The stranger was showing people something; it was hard to see what.",
                                "short": "was showing something", "severity": 0}})
    placed = entry.get("install")
    if isinstance(placed, dict):
        aids = f" using the {' and the '.join(placed['aid_names'])}" if placed["aid_names"] else ""
        views.append({"kind": "demonstration", "victim": None, "item": placed["object_name"], "think": False,
                      "works": True, "audience": [], "clear_cells": SIGHT_CELLS,  # A beam going up: anyone can see it.
                      "clear": {"summary": f"The stranger got the {placed['object_name']} up into the "
                                           f"{placed['into_name']}{aids}.",
                                "short": f"put the {placed['object_name']} in place", "severity": 1},
                      "vague": {"summary": "The stranger was heaving something heavy into place.",
                                "short": "was working on something heavy", "severity": 0}})
    give = entry.get("give")
    if isinstance(give, dict):
        things = " and ".join(give["names"])
        views.append({"kind": "gift", "victim": give["recipient_id"], "item": things, "think": False,
                      "clear": {"summary": f"The stranger gave {give['recipient_name']} a {things}.",
                                "short": f"gave {give['recipient_name']} a {things}", "severity": 1},
                      "vague": {"summary": f"The stranger handed something to {give['recipient_name']}.",
                                "short": f"handed something to {give['recipient_name']}", "severity": 0}})
    return views


SOURCES = {"violence": "victim", "theft": "victim", "gift": "received"}


def perceive(state: dict, entry: dict) -> list[dict]:
    """Memories for everyone who could see what the player just did (and for the people it involved).

    Close witnesses see what happened; those further off only see something going on.
    """
    here = player_cell(state)
    perceptions = []
    for seen in _describe(state, entry):
        victim = find(state["npcs"], seen["victim"] or "")
        involved = {seen["victim"], *seen.get("audience", [])} - {None}
        for npc in state["npcs"]:
            if not npc.get("alive", True):
                continue
            views = []
            if math.dist(_cell(npc), here) <= SIGHT_CELLS and line_of_sight(_cell(npc), here):
                views.append(math.dist(_cell(npc), here))
            if victim is not None and math.dist(_cell(npc), _cell(victim)) <= SIGHT_CELLS \
                    and line_of_sight(_cell(npc), _cell(victim)):
                views.append(math.dist(_cell(npc), _cell(victim)))
            close = npc["id"] in involved
            if not (close or views):
                continue
            clarity = "clear" if close or min(views) <= seen.get("clear_cells", CLEAR_VIEW_CELLS) else "vague"
            source = (SOURCES.get(seen["kind"], "shown") if npc["id"] == seen["victim"] else
                      "shown" if close else "witnessed")
            memory = {"kind": seen["kind"], "victim": seen["victim"], "item": seen.get("item"), **seen[clarity],
                      "clarity": clarity, "at": state["sim_time_ms"], "event": entry.get("event_id"),
                      "source": source}
            if "works" in seen:
                memory["works"] = seen["works"]
            if npc["id"] == seen["victim"]:  # They tell it in the first person: "attacked me", "stole my plank".
                memory["short"] = memory["short"].replace(f"{npc['name']}'s", "my").replace(npc["name"], "me")
            perceptions.append({"npc_id": npc["id"], "memory": memory, "think": seen.get("think", True)})
    return perceptions


def apply_perceptions(state: dict, perceptions: list[dict]) -> None:
    for perception in perceptions:
        npc = find(state["npcs"], perception["npc_id"])
        if npc is None or not npc.get("alive", True):
            continue
        remember(npc, perception["memory"])
        if perception.get("think", True):
            mind(npc)["rethinks"] = 0
            add_pending(state, npc["id"], "decide", perception["memory"]["source"])


# --- Options, lines and deciding ---------------------------------------------------------------

def _family_word(text: str | None) -> str | None:
    """'her nephew Jory' -> 'my nephew'."""
    return next((f"my {word}" for word in FAMILY_WORDS if text and word in text), None)


def _lines(state: dict, npc: dict, action: str, slots: dict) -> list[tuple[str, str]]:
    """Up to two (line_id, text) choices for this action in voices that suit this person."""
    bank = LINES.get(action, {})
    tones = list(card(npc).get("tones") or ["frightened"])
    worst = worst_memory(npc)
    if action == "shout_for_help" and worst and worst["kind"] == "theft":
        tones = ["theft"] + tones
    if worst and is_family(npc, worst.get("victim")):
        tones = ["protective"] + tones
    if not card(npc).get("guard"):
        tones = [t for t in tones if t != "official"]
    available = [t for t in dict.fromkeys(tones) if t in bank] or list(bank)[:1]
    choices = []
    for tone in available:
        for index, template in enumerate(bank[tone]):
            line_id = f"{action}.{tone}.{index}"
            if line_id == mind(npc).get("last_line"):
                continue  # Never the same line twice in a row.
            try:
                choices.append((line_id, template.format(**slots)))
            except KeyError:
                continue
            break  # One line per tone, so the two choices differ in voice.
        if len(choices) == 2:
            break
    return choices


def slots(state: dict, npc: dict) -> dict:
    """Words the line bank fills in for this person: who was hurt, what was taken, their weapon."""
    worst = worst_memory(npc)
    victim = find(state["npcs"], (worst or {}).get("victim") or "")
    family = _family_word(relation(npc, victim["id"])) if victim else None
    return {"victim": victim["name"] if victim else "someone", "relation": family or (victim["name"] if victim else "them"),
            "short": (worst or {}).get("short", "caused trouble"), "item": (worst or {}).get("item") or "things",
            "owner": victim["name"] if victim else "someone", "weapon": card(npc).get("weapon") or "fists",
            "guard": "friend"}


def _options(state: dict, npc: dict) -> dict[str, dict]:
    """Every option code can carry out for this person right now: action, target, line, description."""
    name, me = npc["name"], card(npc)
    worst = worst_memory(npc)
    victim = find(state["npcs"], (worst or {}).get("victim") or "")
    slots_ = slots(state, npc)
    bases: list[tuple[str, str, str | None, str | None]] = [  # (key, description, action for lines, target)
        ("carry_on", f"{name} ignores it and carries on with what they were doing.", None, None),
        ("watch", f"{name} stays where they are and keeps a wary eye on the stranger.", None, None),
        ("flee", f"{name} runs away from the stranger to somewhere safe.", "flee", None)]
    if not me.get("guard"):
        bases.append(("hide", f"{name} slips away out of the stranger's sight and stays hidden.", None, None))
        bases.append(("warn_others", f"{name} calls out to warn people nearby about the stranger.", "warn_others", None))
    if not (worst is not None and worst.get("event") in mind(npc).get("shouted", [])):
        bases.append(("shout_for_help", f"{name} shouts loudly for help and for the guards, right where they are.",
                      "shout_for_help", None))
    if me.get("guard"):
        bases.append(("whistle", f"{name} blows a whistle to call every guard within earshot.", "whistle", None))
    if state["player"].get("alive", True):
        recently = (mind(npc).get("confronted_at") or -10**9) > state["sim_time_ms"] - 60_000
        if not recently:
            bases.append(("confront", f"{name} walks up to the stranger and demands an explanation.", "confront", None))
            if me.get("weapon"):
                bases.append(("threaten", f"{name} walks up to the stranger brandishing their {me['weapon']}, "
                                          "warning them off without striking yet.", "threaten", None))
            if worst and worst["kind"] == "theft" and worst.get("victim") == npc["id"]:
                bases.append(("demand_payment", f"{name} goes to the stranger and demands their {slots_['item']} "
                                                "back or payment for it.", "demand_payment", None))
        weapon = f" with their {me['weapon']}" if me.get("weapon") else " with bare hands"
        bases.append(("attack", f"{name} attacks the stranger{weapon} ({me.get('combat', 'no fighter')}).", "attack", None))
    told = sorted((g for g in state["npcs"] if g["id"] != npc["id"] and g.get("alive", True) and card(g).get("guard")),
                  key=lambda g: math.dist(_cell(g), _cell(npc)))[:2]
    told += [find(state["npcs"], f) for f in card(npc).get("family", [])
             if find(state["npcs"], f) and find(state["npcs"], f).get("alive", True) and find(state["npcs"], f) not in told]
    for person in told:
        steps = round(math.dist(_cell(person), _cell(npc)))
        who = relation(npc, person["id"]) or f"{person['name']} the {card(person)['role']}"
        bases.append((f"report:{person['id']}", f"{name} goes to {who} (about {steps} steps away) and tells them "
                                                f"what happened.", "report", person["name"]))
    if victim and victim["id"] != npc["id"] and victim.get("alive", True) and victim.get("health", 100) < 100:
        bases.append((f"help:{victim['id']}", f"{name} goes to help {victim['name']}, who is hurt.", "help", None))
    options: dict[str, dict] = {}
    for key, description, line_action, spoken_to in bases:
        action, _, target = key.partition(":")
        record = {"action": action, "target": target or None, "line": None, "line_id": None}
        choices = _lines(state, npc, line_action, {**slots_, "guard": spoken_to or slots_["guard"]}) if line_action else []
        if not choices:
            options[key] = {**record, "description": description}
            continue
        for line_id, text in choices:
            options[f"{key}|{line_id}"] = {**record, "line": text, "line_id": line_id,
                                           "description": f"{description} Says: “{text}”"}
    return options


def legal_actions(state: dict, npc: dict) -> dict[str, str]:
    return {key: option["description"] for key, option in _options(state, npc).items()}


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
        source = {"witnessed": "saw from nearby" if memory.get("clarity") != "vague" else "saw from a distance",
                  "victim": "it happened to them", "received": "it was given to them",
                  "shown": "was shown it up close"}.get(memory["source"], memory["source"])
        kind, _, teller = memory["source"].partition(":")
        if kind in ("told_by", "heard") and find(state["npcs"], teller):
            name = find(state["npcs"], teller)["name"]
            source = ("told by " if kind == "told_by" else "heard ") + (relation(npc, teller) or name)
        doubted = " (they doubt this)" if memory.get("doubted") else ""
        who = relation(npc, memory.get("victim"))
        lines.append(f"- ({source}) {memory['summary']}{doubted}" + (f" [{who}]" if who else ""))
    for deal in sorted((a for a in state.get("agreements", {}).values() if a.get("issuer") == npc["id"]
                        and a.get("status") in ("proposed", "accepted", "fulfilled")), key=lambda a: a["id"]):
        status = {"proposed": "offered, not yet agreed", "accepted": "agreed, not yet done",
                  "fulfilled": "done"}[deal["status"]]
        lines.append(f"{me['name']}'s deal with the stranger ({status}): the stranger is to {deal['task']}.")
    feelings = my_mind["feelings"]
    lines.append(f"Feelings toward the stranger: fear {feelings['fear']:.1f} of 1, anger {feelings['anger']:.1f} of 1.")
    others = [f"{n['name']} ({relation(npc, n['id']) or card(n)['role']}, "
              f"{condition(n.get('health', 100), n.get('alive', True))}, {round(math.dist(_cell(n), _cell(npc)))} steps)"
              for n in state["npcs"] if n["id"] != npc["id"] and math.dist(_cell(n), _cell(npc)) <= 16]
    if others:
        lines.append("People nearby: " + "; ".join(others) + ".")
    return "\n".join(lines)


def _questions(state: dict, npc: dict, prefix: str = "") -> dict:
    name = npc["name"]
    questions = {
        f"{prefix}action": {"type": "choice", "criteria": legal_actions(state, npc),
                            "instructions": f"Given who {name} is and what they know, what does {name} do and say "
                                            f"right now?"},
        f"{prefix}fear": {"type": "score", "criteria": FEAR_LEVELS,
                          "instructions": f"How afraid of the stranger is {name} now?"},
        f"{prefix}anger": {"type": "score", "criteria": ANGER_LEVELS,
                           "instructions": f"How angry at the stranger is {name} now?"},
    }
    latest = mind(npc)["memories"][-1] if mind(npc)["memories"] else None
    if latest and latest["source"].startswith(("told_by", "heard")):
        questions[f"{prefix}believes"] = {"type": "noul", "instructions": f"Does {name} believe what they just heard?"}
    return questions


def _brief(state: dict, npc: dict, pending: dict, prefix: str = "") -> tuple[str, dict]:
    """A person's situation and questions: reacting to what they saw, or their next move face to face."""
    if pending["kind"] == "round":
        import encounter
        return encounter.situation(state, npc), encounter.questions(state, npc, prefix)
    return _situation(state, npc), _questions(state, npc, prefix)


def decision_request(state: dict, pending: dict) -> tuple[str, dict]:
    """One person's request (used when a batched answer is missing)."""
    return _brief(state, find(state["npcs"], pending["npc_id"]), pending)


def batch_request(state: dict, batch: list[dict]) -> tuple[str, dict, dict[str, str]]:
    """One request for everyone deciding now: a shared scene plus each person's brief and questions.

    Returns (state text, questions, {npc_id: question prefix}).
    """
    prefixes, sections, questions = {}, [], {}
    for pending in batch:
        npc = find(state["npcs"], pending["npc_id"])
        prefix = npc["id"].split("_")[1] + "__"
        prefixes[npc["id"]] = prefix
        text, asked = _brief(state, npc, pending, prefix)
        sections.append(f"=== {npc['name'].upper()} (questions starting '{prefix}') ===\n{text}")
        questions.update(asked)
    text = ("Several people in a small premodern town are each deciding, independently, how to react to a stranger. "
            "Judge each person only from their own section.\n\n" + "\n\n".join(sections))
    return text, questions, prefixes


def answers_for(answers: dict, prefix: str) -> dict:
    return {key[len(prefix):]: value for key, value in answers.items() if key.startswith(prefix)}


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
                          activity="walk" if job["kind"] in ("flee", "report", "approach", "attack", "vouch")
                          else "look")
        if job["kind"] == "encounter":
            mind(npc)["facing_player"] = True


def _away_goal(state: dict, npc: dict, blocked: set, hidden: bool = False) -> list[int]:
    """A reachable cell far from the stranger; for hiding, one the stranger can't see."""
    _, steps = crafting._bfs(_cell(npc), blocked, 14)
    here = player_cell(state)
    cells = [c for c in steps if not hidden or not line_of_sight(c, here)] or list(steps)
    goal = max(cells, key=lambda c: (math.dist(c, here), -steps[c]))
    return [goal[0], goal[1]]


def _raise_alarm(state: dict, npc: dict, line: str, radius: float, now: int, guards_only: bool = False) -> None:
    """Everyone within earshot who didn't already know hears about it and may react."""
    worst = worst_memory(npc)
    if worst is not None:
        mind(npc).setdefault("shouted", []).append(worst.get("event"))
    for other in state["npcs"]:
        if other["id"] == npc["id"] or not other.get("alive", True) or (guards_only and not card(other).get("guard")):
            continue
        if worst is not None and knows(other, worst.get("event")):
            continue  # Old news to them.
        if math.dist(_cell(other), _cell(npc)) > radius:
            continue
        heard = f"{npc['name']} called out “{line}”"
        memory = {"kind": worst["kind"] if worst else "alarm", "severity": worst["severity"] if worst else 1,
                  "event": worst.get("event") if worst else None, "clarity": "heard",
                  "summary": heard + (f" — {npc['name']} says: {worst['summary']}" if worst else "."),
                  "short": worst["short"] if worst else "caused trouble", "item": (worst or {}).get("item"),
                  "victim": worst["victim"] if worst else None, "at": now, "source": f"heard:{npc['id']}"}
        remember(other, memory)
        mind(other)["rethinks"] = 0
        add_pending(state, other["id"], "decide", f"heard {npc['name']}")
        if card(other).get("guard"):
            for known in mind(npc)["memories"]:
                known["reported"] = True  # A guard heard: the caller has done their part.


def apply_decision(state: dict, npc: dict, answers: dict, now: int, journal: list[dict]) -> dict:
    """Carry out one person's decision (action and line). Returns a short record for the trace."""
    my_mind = mind(npc)
    levels = len(FEAR_LEVELS) - 1
    if "fear" in answers:
        my_mind["feelings"]["fear"] = round(float(answers["fear"]["score"]) / levels, 2)
    if "anger" in answers:
        my_mind["feelings"]["anger"] = round(float(answers["anger"]["score"]) / levels, 2)
    if "believes" in answers and answers["believes"]["noul"] < 0.5 and my_mind["memories"]:
        my_mind["memories"][-1]["doubted"] = True
    options = _options(state, npc)
    choice = answers.get("action", {}).get("choice")
    if choice not in options:  # e.g. the answer named the action without a line: take its first line.
        base = (choice or "").split("|")[0]
        choice = next((key for key in options if key.split("|")[0] == base), None) or \
            next(key for key in options if key.startswith("watch"))
    option = options[choice]
    action, target, line, line_id = option["action"], option["target"], option["line"], option["line_id"]
    blocked = crafting._blocked_cells(state)
    if action == "carry_on":
        _set_job(npc, None, now)
    elif action == "watch":
        _set_job(npc, {"kind": "watch", "until": now + 20_000}, now)
    elif action in ("flee", "hide"):
        if line:
            _say(npc, line, now, state, journal, line_id)
        _set_job(npc, {"kind": "flee", "goal": _away_goal(state, npc, blocked, hidden=action == "hide"),
                       "speed": "run", "until": now + 40_000}, now)
    elif action in ("shout_for_help", "warn_others", "whistle"):
        _say(npc, line or "Guards!", now, state, journal, line_id)
        radius = {"shout_for_help": HEAR_SHOUT_CELLS, "warn_others": WARN_CELLS, "whistle": WHISTLE_CELLS}[action]
        _raise_alarm(state, npc, line or "Guards!", radius, now, guards_only=action == "whistle")
        _set_job(npc, {"kind": "watch", "until": now + 20_000}, now)
    elif action == "report":
        _set_job(npc, {"kind": "report", "target": target, "speed": "run", "line": line, "line_id": line_id}, now)
    elif action in ("confront", "threaten", "demand_payment"):
        my_mind["confronted_at"] = now
        _set_job(npc, {"kind": "approach", "target": "player", "stop": 2.5 if action == "threaten" else 2.0,
                       "speed": "walk", "then": action, "line": line, "line_id": line_id}, now)
    elif action == "attack":
        if line:
            _say(npc, line, now, state, journal, line_id)
        _set_job(npc, {"kind": "attack", "target": "player", "speed": "run", "next_at": now}, now)
    elif action == "help":
        _set_job(npc, {"kind": "approach", "target": target, "stop": 1.5, "speed": "walk", "then": "help",
                       "line": line, "line_id": line_id}, now)
    return {"npc_id": npc["id"], "action": choice, "feelings": dict(my_mind["feelings"])}


def strike(state: dict, npc: dict, now: int, journal: list[dict]) -> dict:
    """An NPC's blow against the player: a seeded roll on weapon and skill (no model call)."""
    player = state["player"]
    weapon = card(npc).get("weapon") or "fists"
    stats = WEAPONS.get(weapon, WEAPONS["fists"])
    skill = int(card(npc).get("skill", 0))
    rng = random.Random(f"{state.get('run_id')}:{npc['id']}:{now}")
    health = player.get("health", 100)
    result = "missed"
    if rng.random() < stats["hit"] + 0.05 * skill:
        finishing = stats["kill"] + (0.1 if health <= 30 else 0.0)
        damage = round(stats["damage"] * (0.8 + 0.4 * rng.random()))
        health = 0 if rng.random() < finishing else max(0, health - damage)
        result = "killed" if health == 0 else "wounded"
    player.update(health=health, alive=health > 0)
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
                _set_job(other, {"kind": "watch", "until": now + 20_000}, now)
    return {"npc_id": npc["id"], "result": result}


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


def _deliver_report(state: dict, npc: dict, target: dict, now: int, journal: list[dict], job: dict) -> None:
    worst = worst_memory(npc)
    if worst is None:
        return
    _say(npc, job.get("line") or f"{target['name']}! The stranger {worst['short']}!", now, state, journal,
         job.get("line_id"))
    for known in mind(npc)["memories"]:
        known["reported"] = True  # The teller has done their part.
    if knows(target, worst.get("event")):
        return
    memory = {**{k: worst.get(k) for k in ("kind", "severity", "short", "victim", "item")}, "event": worst.get("event"),
              "clarity": "told", "summary": f"{npc['name']} told them: {worst['summary']}", "at": now,
              "source": f"told_by:{npc['id']}"}
    remember(target, memory)
    mind(target)["rethinks"] = 0
    add_pending(state, target["id"], "decide", f"told by {npc['name']}")


def _deliver_vouch(state: dict, npc: dict, captain: dict, now: int, journal: list[dict], job: dict) -> None:
    """Someone speaks for the stranger to the captain: evidence he weighs when the stranger asks to enter."""
    choices = _lines(state, npc, "vouch", {"why": job["why"]})
    line_id, text = choices[0] if choices else (None, f"Captain, I'll speak for the stranger: {job['why']}")
    _say(npc, text, now, state, journal, line_id)
    remember(captain, {"kind": "vouch", "severity": 1, "by": npc["id"], "victim": None, "item": None,
                       "event": job.get("event"), "clarity": "told", "source": f"told_by:{npc['id']}", "at": now,
                       "summary": job["summary"], "short": f"has {npc['name']}'s word"})


def _gate_watch(state: dict, npcs: list[dict], now: int) -> None:
    """No model involved: the nearest free guard walks up to a stranger at the gate who hasn't been admitted."""
    x, y = player_cell(state)
    guards = [g for g in npcs if g.get("alive", True) and card(g).get("guard")]
    if state.get("admitted") or state.get("inside_city") or not state["player"].get("alive", True)             or not (GATE_ZONE[0] <= x <= GATE_ZONE[1] and y <= GATE_ZONE[2]):
        for guard in guards:  # The stranger left (or may pass): nobody needs stopping.
            if ((guard.get("mind") or {}).get("job") or {}).get("then") == "halt":
                _set_job(guard, None, now)
        return
    if any((g.get("mind") or {}).get("halted_at", -10**9) > now - HALT_EVERY_MS
           or ((g.get("mind") or {}).get("job") or {}).get("then") == "halt" for g in guards):
        return
    free = [g for g in guards if not (g.get("mind") or {}).get("job")
            and math.dist(_cell(g), (x, y)) <= HALT_REACH_CELLS]
    if free:
        guard = min(free, key=lambda g: math.dist(_cell(g), (x, y)))
        _set_job(guard, {"kind": "approach", "target": "player", "stop": 2.0, "speed": "walk", "then": "halt"}, now)


def _maybe_reconsider(state: dict, npc: dict, why: str) -> None:
    """Someone shaken by a serious event nobody official has heard about thinks again (a few times at most)."""
    my_mind = mind(npc)
    worst = worst_memory(npc)
    if worst is None or worst["severity"] < 2 or worst.get("reported") or card(npc).get("guard"):
        return
    if my_mind.get("rethinks", 0) >= MAX_RETHINKS or not state["player"].get("alive", True):
        return
    my_mind["rethinks"] = my_mind.get("rethinks", 0) + 1
    add_pending(state, npc["id"], "decide", why)


def _ambient(state: dict, npc: dict, now: int, blocked: set) -> None:
    """No model involved: wary people face the stranger; frightened people keep their distance."""
    my_mind = npc.get("mind")
    if not my_mind or my_mind.get("job") or not state["player"].get("alive", True):
        if my_mind is not None:
            my_mind["facing_player"] = bool(my_mind.get("job")) and my_mind["job"]["kind"] in ("watch", "approach", "attack")
        return
    feelings = my_mind.get("feelings", {})
    distance = math.dist(_cell(npc), player_cell(state))
    wary = feelings.get("fear", 0) > 0.3 or feelings.get("anger", 0) > 0.3
    my_mind["facing_player"] = wary and distance <= AMBIENT_CELLS
    if feelings.get("fear", 0) > 0.6 and distance < 5:
        _set_job(npc, {"kind": "flee", "goal": _away_goal(state, npc, blocked), "speed": "walk",
                       "until": now + 10_000}, now)


def advance_world(state: dict, elapsed_ms: int, now: int) -> tuple[list[dict], list[dict], dict]:
    """People follow routines or their current job for elapsed_ms; blows are rolled; ambient rules apply.

    Returns (npcs, journal lines, player). May queue thinking in state["pending_minds"].
    """
    import encounter  # People who reach the stranger start or join an encounter (encounter imports minds).

    npcs = npc_sim.advance_npcs(state["npcs"], elapsed_ms, now, crafting.m2._GEOMETRY)
    working = copy.copy(state)
    working["npcs"] = npcs
    working["player"] = copy.deepcopy(state["player"])
    working["encounter"] = copy.deepcopy(state.get("encounter"))
    journal: list[dict] = []
    blocked = crafting._blocked_cells(state)
    end = now + elapsed_ms
    for npc in npcs:
        job = (npc.get("mind") or {}).get("job")
        if not npc.get("alive", True):
            continue
        if not job:
            _ambient(working, npc, end, blocked)
            continue
        if job["kind"] == "encounter":
            continue  # Face to face with the stranger: acts in rounds, not on the clock.
        if job.get("wait_until", 0) > end:
            continue  # e.g. an attacker the stranger just walked away from, a moment before they give chase.
        if job["kind"] == "watch":
            if end >= job["until"]:
                _set_job(npc, None, end)
                _maybe_reconsider(working, npc, "still shaken")
            continue
        goal = _target_cell(working, npcs, job)
        if goal is None or (job["kind"] == "attack" and math.dist(_cell(npc), goal) > GIVE_UP_CELLS):
            _set_job(npc, None, end)
            continue
        stop = {"flee": 0.0, "report": 1.5, "attack": 1.5, "vouch": 1.5}.get(job["kind"], job.get("stop", 1.5))
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
                _deliver_report(working, npc, target, end, journal, job)
            _set_job(npc, {"kind": "watch", "until": end + 15_000}, end)
        elif job["kind"] == "vouch":
            captain = find(npcs, job["target"])
            if captain:
                _deliver_vouch(working, npc, captain, end, journal, job)
            _set_job(npc, {"kind": "watch", "until": end + 15_000}, end)
        elif job["kind"] == "approach" and job.get("then") == "halt":
            choices = _lines(working, npc, "halt", {})
            line_id, text = choices[0] if choices else (None, "Halt! State your business.")
            _say(npc, text, end, working, journal, line_id, category="halt")
            mind(npc)["halted_at"] = end
            mind(npc).setdefault("talk", []).append({"who": "them", "text": text, "at": end})
            encounter.join(working, npc, "halt", text, end)
        elif job["kind"] == "approach" and job.get("then") in ("confront", "threaten", "demand_payment"):
            text = job.get("line") or "What do you think you're doing?!"
            _say(npc, text, end, working, journal, job.get("line_id"), category="address")
            mind(npc).setdefault("talk", []).append({"who": "them", "text": text, "at": end})
            encounter.join(working, npc, job["then"], text, end)
        elif job["kind"] == "approach":
            if job.get("line"):
                _say(npc, job["line"], end, working, journal, job.get("line_id"))
            _set_job(npc, {"kind": "watch", "until": end + 20_000}, end)
            controller["activity"] = "work"
            _maybe_reconsider(working, npc, "tending the hurt person")
        elif job["kind"] == "attack":
            encounter.join(working, npc, "attack", None, end)  # Blows happen in the encounter's rounds.
    if not working.get("encounter"):
        _gate_watch(working, npcs, end)  # Nobody needs halting while the stranger is already face to face with someone.
    encounter.prune(working)
    state["pending_minds"] = working.get("pending_minds", state.get("pending_minds", []))
    state["encounter"] = working.get("encounter")
    return npcs, journal, working["player"]
