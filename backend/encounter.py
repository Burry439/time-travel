"""Encounters: face to face with the stranger, in simultaneous rounds.

Anyone who comes up to address the stranger (a guard's halt, a confrontation, a threat, a demand
for payment, an attacker reaching them) opens or joins an encounter; so does the stranger speaking
to someone. Time then moves in rounds instead of on the clock:

1. At the start of a round each person in it commits an intent (listen, attack, shout or whistle
   for help, flee, leave), chosen by Jev from the situation as it stands, before they know what
   the stranger will do. The thinking lane decides these while the player is still typing.
2. The player acts: say something, do something (a Try Something), wait, or walk away.
3. Code resolves everything at once, in a seeded initiative order: a blow that drops someone first
   stops what they were about to do; otherwise both happen, a sword swung while words are spoken.
4. The person the stranger addressed, if they were listening and are still standing, replies to
   what actually happened (talk.py: Jev chooses, the voice says it).
5. The world moves on by the round's length (longer for long actions, which cost extra blows),
   so others can walk up and join. The next round's intents are queued.

The whole round is one event. The encounter ends when everyone in it has gone or died, the
stranger walks away, the stranger dies, or the captain admits them.
"""
from __future__ import annotations

import copy
import math
import random

import crafting
import minds
import talk

ROUND_MS = 5_000
LEAVE_MS = 1_000  # Walking away takes a moment; attackers are left a step behind.
PURSUIT_DELAY_MS = 2_500
MAX_EXTRA_BLOWS = 4
LOG_KEPT = 30
OPENING_INTENT = {"attack": "attack"}  # Everyone else opens by listening: they came to talk (or to be answered).
REASON_WORDS = {"halt": "a guard stopped the stranger at the gate", "confront": "they confronted the stranger",
                "threaten": "they came to threaten the stranger", "demand_payment": "they came to demand payment",
                "attack": "they attacked the stranger", "talk": "the stranger spoke to them"}


# --- Opening, joining and ending ------------------------------------------------------------------

def active(state: dict) -> dict | None:
    return state.get("encounter") or None


def hostile(state: dict) -> bool:
    """An encounter the stranger can't simply walk off from: anything but a conversation they began."""
    encounter = active(state)
    return bool(encounter) and encounter["reason"] != "talk"


def join(state: dict, npc: dict, reason: str, line: str | None, now: int) -> dict:
    """Open an encounter with this person, or bring them into the current one."""
    encounter = active(state)
    if encounter is None:
        encounter = state["encounter"] = {
            "id": f"enc_{state.get('event_seq', 0) + 1}_{npc['id'][4:]}", "participants": [], "opened_by": npc["id"]
            if reason != "talk" else "player", "reason": reason, "round": 1, "intents": {}, "log": [],
            "started_at": now}
    elif reason != "talk" and encounter["reason"] == "talk":
        encounter["reason"] = reason  # Someone came to confront the stranger mid-conversation: no longer a chat.
    if npc["id"] not in encounter["participants"]:
        encounter["participants"].append(npc["id"])
        encounter["intents"][npc["id"]] = {"action": OPENING_INTENT.get(reason, "listen"), "line": None,
                                           "line_id": None}
        _log(encounter, npc["id"], "arrive", f"{npc['name']}: “{line}”" if line else
             f"{npc['name']} comes at you." if reason == "attack" else f"{npc['name']} faces you.")
    if reason != "talk":
        minds._set_job(npc, {"kind": "encounter"}, now)
    # Face to face, people act in rounds: they don't also stop to think about what they saw.
    state["pending_minds"] = [p for p in state.get("pending_minds", [])
                              if not (p["npc_id"] == npc["id"] and p["kind"] == "decide")]
    return encounter


def _log(encounter: dict, who: str, kind: str, text: str, seen: str | None = None) -> dict:
    entry = {"round": encounter["round"], "who": who, "kind": kind, "text": text}
    if seen:
        entry["seen"] = seen
    encounter["log"].append(entry)
    del encounter["log"][:-LOG_KEPT]
    return entry


def prune(state: dict) -> None:
    """Drop people who are dead or have wandered off from a conversation; end it when nobody is left."""
    encounter = active(state)
    if encounter is None:
        return
    here = minds.player_cell(state)
    keep = []
    for npc_id in encounter["participants"]:
        npc = minds.find(state["npcs"], npc_id)
        if npc is None or not npc.get("alive", True):
            continue
        job = (npc.get("mind") or {}).get("job") or {}
        if encounter["reason"] == "talk" and (job.get("kind") not in (None, "watch", "encounter")
                                              or math.dist(minds._cell(npc), here) > 6):
            continue  # Went off to do something else.
        keep.append(npc_id)
    encounter["participants"] = keep
    encounter["intents"] = {k: v for k, v in encounter["intents"].items() if k in keep}
    if not keep or not state["player"].get("alive", True) or state.get("inside_city"):
        end(state, state.get("sim_time_ms", 0))


def end(state: dict, now: int, walked_away: bool = False) -> None:
    """Everyone goes back to their day; anyone set on attacking gives chase a moment later."""
    encounter = active(state)
    if encounter is None:
        return
    for npc_id in encounter["participants"]:
        npc = minds.find(state["npcs"], npc_id)
        if npc is None or not npc.get("alive", True):
            continue
        attacking = (encounter["intents"].get(npc_id) or {}).get("action") == "attack"
        if walked_away and attacking and state["player"].get("alive", True):
            minds._set_job(npc, {"kind": "attack", "target": "player", "speed": "run", "next_at": now,
                                 "wait_until": now + PURSUIT_DELAY_MS}, now)
        elif ((npc.get("mind") or {}).get("job") or {}).get("kind") in (None, "encounter"):
            minds._set_job(npc, {"kind": "watch", "until": now + 15_000}, now)
    state["pending_minds"] = [p for p in state.get("pending_minds", []) if p["kind"] != "round"]
    state["encounter"] = None


# --- Intents (what each person commits to at the start of a round) -------------------------------

def intent_options(state: dict, npc: dict) -> dict[str, dict]:
    """What this person could do in the next few seconds face to face with the stranger."""
    name, me = npc["name"], minds.card(npc)
    bases = [("listen", f"{name} stays face to face with the stranger and deals with them in words: listens and "
                        f"answers.", None)]
    if state["player"].get("alive", True):
        weapon = f" with their {me['weapon']}" if me.get("weapon") else " with bare hands"
        bases.append(("attack", f"{name} attacks the stranger{weapon} ({me.get('combat', 'no fighter')}).",
                      "attack"))
    shout = "whistle" if me.get("guard") else "shout_for_help"
    bases.append((shout, f"{name} " + ("blows a whistle to bring every guard within earshot."
                                       if me.get("guard") else "shouts for help and for the guards."), shout))
    bases.append(("flee", f"{name} breaks away and runs from the stranger.", "flee"))
    bases.append(("leave", f"{name} has had enough of the stranger and walks off, leaving them be.", None))
    words = minds.slots(state, npc)
    options = {}
    for key, description, line_action in bases:
        choices = minds._lines(state, npc, line_action, words) if line_action else []
        if not choices:
            options[key] = {"action": key, "line": None, "line_id": None, "description": description}
        for line_id, text in choices:
            options[f"{key}|{line_id}"] = {"action": key, "line": text, "line_id": line_id,
                                           "description": f"{description} Says: “{text}”"}
    return options


def situation(state: dict, npc: dict) -> str:
    encounter = active(state) or {"round": 1, "reason": "talk", "log": []}
    view = minds.regard(npc)
    lines = [minds._situation(state, npc),
             f"How {npc['name']} regards the stranger: trust {view['trust']:.2f} of 1, suspicion "
             f"{view['suspicion']:.2f} of 1.",
             f"{npc['name']} is face to face with the stranger (round {encounter['round']}; it began because "
             f"{REASON_WORDS.get(encounter['reason'], 'they met')})."]
    recent = [e.get("seen") or e["text"] for e in encounter["log"][-8:]]
    if recent:
        lines.append("What has happened between them so far, oldest first:")
        lines += [f"- {text}" for text in recent]
    return "\n".join(lines)


def questions(state: dict, npc: dict, prefix: str = "") -> dict:
    name = npc["name"]
    return {
        f"{prefix}action": {"type": "choice", "criteria": {k: o["description"] for k, o in intent_options(state, npc).items()},
                            "instructions": f"What does {name} do in the next few seconds? {name} commits to this "
                                            f"before seeing what the stranger does next."},
        f"{prefix}fear": {"type": "score", "criteria": minds.FEAR_LEVELS,
                          "instructions": f"How afraid of the stranger is {name} now?"},
        f"{prefix}anger": {"type": "score", "criteria": minds.ANGER_LEVELS,
                           "instructions": f"How angry at the stranger is {name} now?"},
    }


def set_intent(state: dict, npc: dict, answers: dict) -> dict:
    """Commit Jev's choice as this person's intent for the current round (and their feelings)."""
    encounter = active(state)
    if encounter is None or npc["id"] not in encounter["participants"]:
        return {"npc_id": npc["id"], "skipped": "no longer in the encounter"}
    feelings = minds.mind(npc)["feelings"]
    if "fear" in answers:
        feelings["fear"] = round(float(answers["fear"]["score"]) / (len(minds.FEAR_LEVELS) - 1), 2)
    if "anger" in answers:
        feelings["anger"] = round(float(answers["anger"]["score"]) / (len(minds.ANGER_LEVELS) - 1), 2)
    options = intent_options(state, npc)
    choice = (answers.get("action") or {}).get("choice")
    if choice not in options:
        base = (choice or "").split("|")[0]
        choice = next((k for k in options if k.split("|")[0] == base), "listen")
    option = options[choice]
    encounter["intents"][npc["id"]] = {"action": option["action"], "line": option["line"],
                                       "line_id": option["line_id"]}
    if option["action"] == "attack" and encounter["reason"] == "talk":
        encounter["reason"] = "attack"  # The conversation turned into a fight.
    return {"npc_id": npc["id"], "action": choice, "feelings": dict(feelings)}


def missing_intents(state: dict) -> list[str]:
    encounter = active(state)
    return [] if encounter is None else [n for n in encounter["participants"] if n not in encounter["intents"]]


def intent_request(state: dict, npc_ids: list[str]) -> tuple[str, dict, dict[str, str]]:
    """One Jev request for everyone in the encounter who hasn't committed yet."""
    return minds.batch_request(state, [{"npc_id": n, "kind": "round", "why": "encounter"} for n in npc_ids])


# --- Resolving a round ------------------------------------------------------------------------------

def _initiative(state: dict, encounter: dict, run_id: str) -> list[str]:
    """Who acts first when it matters: a seeded roll, plus fighting skill for NPCs."""
    rolls = {"player": random.Random(f"{run_id}:{encounter['id']}:{encounter['round']}:player").random()}
    for npc_id in encounter["participants"]:
        npc = minds.find(state["npcs"], npc_id)
        rng = random.Random(f"{run_id}:{encounter['id']}:{encounter['round']}:{npc_id}")
        rolls[npc_id] = rng.random() + 0.1 * int(minds.card(npc).get("skill", 0))
    return sorted(rolls, key=lambda who: (-rolls[who], who))


def _close_in(state: dict, npc: dict) -> bool:
    """An attacker comes within reach this round if they can get there; True if they're within reach."""
    goal = minds.player_cell(state)
    blocked = crafting._blocked_cells(state)
    for _ in range(ROUND_MS // minds.RUN_STEP_MS):
        if math.dist(minds._cell(npc), goal) <= 1.5:
            return True
        step = minds._next_step(minds._cell(npc), goal, 1.5, blocked)
        if step is None:
            return False
        npc["x"], npc["y"] = step
    return math.dist(minds._cell(npc), goal) <= 1.5


def open_for_talk(state: dict, npc: dict, now: int) -> dict:
    """The stranger speaks to someone: a conversation, which is an encounter too."""
    return join(state, npc, "talk", None, now)


def resolve(state: dict, run_id: str, action: dict, judged: dict | None, service_error: str | None,
            trace_id: str) -> tuple[dict, dict]:
    """The physical part of a round, on a copy of the world: everyone's actions in initiative order.

    Returns (draft world, round record: log entries, who replies, effort, what happened in words).
    The reply and time passing are applied afterwards by finish().
    """
    draft = copy.deepcopy(state)
    now, journal = draft["sim_time_ms"], []
    if active(draft) is None:
        open_for_talk(draft, minds.find(draft["npcs"], action["target_id"]), now)
    encounter = draft["encounter"]
    kind, text = action["kind"], action.get("text", "")
    record = {"round": encounter["round"], "entries": [], "effort_seconds": 0, "entry": None, "replier": None,
              "happened": [], "walked_away": False, "verdict": None, "intents": copy.deepcopy(encounter["intents"])}

    def note(who, entry_kind, words, seen=None):
        record["entries"].append(_log(encounter, who, entry_kind, words, seen))
        if seen:
            record["happened"].append(seen)

    for who in _initiative(draft, encounter, run_id):
        if not draft["player"].get("alive", True):
            break
        if who == "player":
            if kind == "say":
                note("player", "say", f"You: “{talk.clean(text)}”")
            elif kind == "wait":
                note("player", "wait", "You wait and say nothing.", "The stranger waits and says nothing.")
            elif kind == "leave":
                record["walked_away"] = True
                note("player", "leave", "You turn and walk away.", "The stranger turns and walks away.")
            elif kind == "do":
                payload, verdict, _ = crafting.resolve_attempt(draft, run_id, text, judged, service_error,
                                                               trace_id, now)
                crafting.apply_payload(draft, payload)
                draft["sim_time_ms"] = now  # Time passes once, for the whole round.
                entry = payload["journal_entry"]
                record["entry"], record["effort_seconds"], record["verdict"] = entry, verdict["effort_seconds"], verdict
                perceptions = minds.perceive(draft, entry)
                minds.apply_perceptions(draft, perceptions)
                inside = set(encounter["participants"])
                draft["pending_minds"] = [p for p in draft.get("pending_minds", [])
                                          if not (p["npc_id"] in inside and p["kind"] == "decide")]
                seen = next((p["memory"]["summary"] for p in perceptions
                             if p["npc_id"] in inside and p["memory"].get("clarity") != "vague"), None)
                note("player", "do", entry["reason"], seen or f"The stranger tried to: “{talk.clean(text)}”")
            continue
        npc = minds.find(draft["npcs"], who)
        intent = encounter["intents"].get(who) or {"action": "listen"}
        if npc is None or not npc.get("alive", True):
            continue
        act, line = intent["action"], intent.get("line")
        if act == "attack":
            if line:
                minds._say(npc, line, now, draft, journal, intent.get("line_id"))
            if not _close_in(draft, npc):
                note(who, "attack", f"{npc['name']} can't reach you.", f"{npc['name']} tried to reach the stranger.")
                continue
            blow = minds.strike(draft, npc, now, journal)
            said = f"{npc['name']}: “{line}” " if line else ""
            note(who, "strike", said + journal[-1]["reason"],
                 f"{npc['name']} struck at the stranger: {blow['result']}.")
        elif act in ("shout_for_help", "whistle"):
            words = line or "Guards!"
            minds._say(npc, words, now, draft, journal, intent.get("line_id"))
            radius = minds.WHISTLE_CELLS if act == "whistle" else minds.HEAR_SHOUT_CELLS
            minds._raise_alarm(draft, npc, words, radius, now, guards_only=act == "whistle")
            note(who, act, f"{npc['name']}: “{words}”", f"{npc['name']} called for help.")
        elif act in ("flee", "leave"):
            if line:
                minds._say(npc, line, now, draft, journal, intent.get("line_id"))
            if act == "flee":
                goal = minds._away_goal(draft, npc, crafting._blocked_cells(draft))
                minds._set_job(npc, {"kind": "flee", "goal": goal, "speed": "run", "until": now + 40_000}, now)
            else:
                minds._set_job(npc, {"kind": "watch", "until": now + 10_000}, now)
            encounter["participants"].remove(who)
            note(who, act, (f"{npc['name']}: “{line}” " if line else "") +
                 (f"{npc['name']} runs off." if act == "flee" else f"{npc['name']} turns away and leaves you be."))
    # A long action in the middle of a fight costs more blows.
    extra = 0
    if record["effort_seconds"] * 1000 > ROUND_MS:
        extra = min(MAX_EXTRA_BLOWS, int((record["effort_seconds"] * 1000 - ROUND_MS) // minds.ATTACK_INTERVAL_MS))
    for n in range(extra):
        for who in list(encounter["participants"]):
            npc = minds.find(draft["npcs"], who)
            if (encounter["intents"].get(who) or {}).get("action") == "attack" and npc.get("alive", True) \
                    and draft["player"].get("alive", True):
                minds.strike(draft, npc, now + (n + 1) * minds.ATTACK_INTERVAL_MS, journal)
                note(who, "strike", journal[-1]["reason"] + " (while you were busy)")
    draft["journal"].extend(journal)
    encounter["participants"] = [n for n in encounter["participants"]
                                 if (npc := minds.find(draft["npcs"], n)) and npc.get("alive", True)]
    # Who answers: the person addressed, if they were listening and are still there.
    target = action.get("target_id") if action.get("target_id") in encounter["participants"] else next(
        (n for n in [encounter["opened_by"]] + encounter["participants"] if n in encounter["participants"]), None)
    if target and draft["player"].get("alive", True) and not record["walked_away"] \
            and (encounter["intents"].get(target) or {}).get("action") == "listen":
        record["replier"] = target
    return draft, record


def finish(draft: dict, record: dict, now: int, reply: dict | None = None) -> None:
    """After the reply (if any): keep or end the encounter and queue the next round's intents."""
    encounter = active(draft)
    if encounter is None:
        return
    if reply:
        encounter["log"].append({"round": record["round"], "who": reply["npc_id"], "kind": "reply",
                                 "text": f"{reply['name']}: “{reply['line']}”"})
        record["entries"].append(encounter["log"][-1])
    over = (record["walked_away"] or not draft["player"].get("alive", True) or bool(draft.get("admitted"))
            or not encounter["participants"])
    if over:
        end(draft, now, walked_away=record["walked_away"])
        record["ended"] = True
        return
    record["ended"] = False
    encounter["round"] += 1
    encounter["intents"] = {}
    for npc_id in encounter["participants"]:
        npc = minds.find(draft["npcs"], npc_id)
        if encounter["reason"] != "talk":
            minds._set_job(npc, {"kind": "encounter"}, now)  # Stay face to face (a reply may have set a watch).
        minds.add_pending(draft, npc_id, "round", "encounter")


def round_ms(record: dict) -> int:
    if record["walked_away"]:
        return LEAVE_MS
    return max(ROUND_MS, record["effort_seconds"] * 1000)
