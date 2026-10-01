"""Conversations (D-44, D-46): the voice model reads the moment, talks and picks the move; code applies.

1. The reply reads the moment, as this person: how the exchange changed their view of the
   stranger, their anger, whether they believe what was said, and (when it matters) whether a deal
   was agreed or done and whether a guard has reason enough to let the stranger in.
2. Code builds the moves this person may make now: tell something they actually know, send them to
   someone, offer a deal, lend or give, demand stolen goods back, take them back, arrest, attack,
   fetch a guard, refuse, tell them to leave, end it, or simply talk. Moves that need a belief
   (letting someone in, a deal) are checked by code against that same reading.
3. The voice model (ai/voice.py) says what this person would say, in their own voice, knowing why
   they are here, and picks one of those moves. Ordinary talk (directions, an apology accepted or
   not, a question back) needs no menu.
4. Code applies every effect: regard (capped: words alone earn only a little goodwill; more needs
   new evidence), what the player learned (their journal), the move, and memories for anyone close
   enough to overhear.

Deals (GDD 6.6) come from each person's authored offers: the person may offer one; whether the stranger
accepted, and later whether they have done it, are yes/no questions in the same request, answered
only from what that person has seen or been given. The reward is a job: the person walks to the
captain and speaks for the stranger. Any guard may let the stranger in for their own reasons (D-43), never
while they know of a crime by the stranger.
"""

from __future__ import annotations

import re

import cast
import combat
import conversation
import encounter
import gatekeeping
import gear
import persona
import reputation
import tuning
from shapes import Npc, State

TURNS_KEPT = 12  # Lines kept verbatim; whole conversations live on as episodes (D-36).


ERRAND_JOBS = ("tell", "vouch", "report")  # Jobs that take someone somewhere to do something (D-54).


def update_regard(npc: Npc, answers: dict) -> dict:
    """Apply the reply's reading. Words alone move regard only so far either way (goodwill, which new evidence
    renews; ill will, capped the same): deeds and crimes move it in full, through what people see (D-46)."""
    view = reputation.regard(npc)
    evidence = {m.get("event") for m in cast.mind(npc)["memories"] if reputation.is_evidence(m)}
    budget = max(0.0, tuning.TALK_GOODWILL + tuning.EVIDENCE_GOODWILL * len(evidence) - view["goodwill_used"])
    grudge = max(0.0, tuning.TALK_ILLWILL - view.setdefault("illwill_used", 0.0))
    before = dict(view)
    trust, suspicion = (
        tuning.SHIFTS[conversation.level(answers, "impression")],
        tuning.SHIFTS[conversation.level(answers, "suspicion")],
    )
    if trust > 0:
        trust = min(trust, budget)
        budget -= trust
    else:
        trust = -min(-trust, grudge)
        grudge -= -trust
    if suspicion < 0:
        suspicion = -min(-suspicion, budget)
    else:
        suspicion = min(suspicion, grudge)
    view["goodwill_used"] = round(view["goodwill_used"] + max(trust, 0.0) + max(-suspicion, 0.0), 3)
    view["illwill_used"] = round(view["illwill_used"] + max(-trust, 0.0) + max(suspicion, 0.0), 3)
    view["trust"] = round(min(1.0, max(0.0, view["trust"] + trust)), 3)
    view["suspicion"] = round(min(1.0, max(0.0, view["suspicion"] + suspicion)), 3)
    reputation.regard_cue(npc, before, view)
    return {"trust": round(trust, 3), "suspicion": round(suspicion, 3)}


def plain_note(name: str, text: str, happened: str | None, line: str) -> str:
    """What someone remembers of an exchange when the voice model gave no note."""
    them = (
        f"The stranger said “{conversation.clean(text)[:140]}”"
        if text.strip()
        else f"The stranger {conversation.clean(happened or 'said nothing')[:140]}"
    )
    return f"{them}; {name} replied “{line[:140]}”."


def _remember_exchange(
    npc: Npc, text: str, happened: str | None, line: str, note: str, name_given: str, doubted: bool, now: int
) -> None:
    """The person's own memory of this exchange (D-36): a note, the stranger's name, a claim they doubt."""
    memory = persona.knows(npc)
    note = " ".join((note or "").split())[:300] or plain_note(npc["name"], text, happened, line)
    memory["notes"] = (memory["notes"] + [note])[-persona.NOTES_KEPT :]
    given = " ".join((name_given or "").split())[:40]
    if given and re.search(rf"\b{re.escape(given)}\b", text, re.IGNORECASE):  # Only a name they actually said.
        memory["name"] = given
    if doubted and text.strip():
        memory["claims"] = (memory["claims"] + [{"text": conversation.clean(text)[:160], "at": now}])[-6:]


def errand(state: State, npc: Npc, to: str, message: str) -> tuple[dict, str] | None:
    """A go-and-tell errand the voice described, if it names a real person (by id or name) and says something."""
    words = " ".join((message or "").split())[:240]
    other = cast.find(state["npcs"], to or "") or next(
        (n for n in state["npcs"] if (to or "").strip().lower() in (n["name"].lower(), n["name"].split()[0].lower())),
        None,
    )
    if other is None or other["id"] == npc["id"] or not other.get("alive", True) or not words:
        return None
    return other, words


def exchange(
    state: State,
    npc_id: str,
    text: str,
    answers: dict,
    key: str,
    line: str,
    walk: list[list[int]],
    happened: str | None = None,
    note: str = "",
    name_given: str = "",
    errand_to: str = "",
    errand_message: str = "",
) -> dict:
    """Commit one exchange on a draft world. Returns the talk fields of the event payload."""
    now, event_id = state["sim_time_ms"], state["event_seq"] + 1
    if walk:
        state["player"].update(x=walk[-1][0], y=walk[-1][1])
    npc = cast.find(state["npcs"], npc_id)
    my_mind = cast.mind(npc)
    options = conversation.replies(state, npc)
    key = key if key in options else "answer"
    act, target = options[key]["act"], options[key]["target"]
    task = errand(state, npc, errand_to, errand_message) if act == "go_tell" else None
    if act == "go_tell" and task is None:
        key, act, target = "answer", "answer", None  # An errand to nobody, or with nothing to say.
    fighting = npc_id in ((state.get("fight") or {}).get("attackers") or [])
    errand_before = dict(my_mind["job"]) if (my_mind.get("job") or {}).get("kind") in ERRAND_JOBS else None
    change = _take_in(npc, answers, text, happened, key, line, note, name_given, now, event_id)
    learned, lent, agreements = [], [], state.setdefault("agreements", {})
    reward_job = _settle_deals(state, npc, answers, line, event_id, learned)
    if act == "vouch":
        reward_job = (
            "I've come to trust them.",
            f"{npc['name']} vouched for the stranger and says they can be trusted.",
        )
    admission = _hand_over(state, npc, act, target, line, event_id, learned, lent)
    if reward_job and npc_id != cast.captain_id(state):
        my_mind["vouched"] = True
        gatekeeping.speak_for(state, npc, reward_job[0], reward_job[1], event_id, now)
    else:
        _then(state, npc, act, target, task, fighting, line, event_id, now, learned, lent)
    if errand_before and ((my_mind.get("job") or {}).get("kind") in (None, "watch")):
        cast.set_job(npc, errand_before, now)  # A word in passing doesn't cancel an errand (D-54).
    _overheard(state, npc, text, line, event_id, now)
    name = npc["name"]
    entry = {
        "kind": "talk",
        "category": "talk",
        "npc_id": npc_id,
        "text": conversation.clean(text),
        "reply": line,
        "act": key,
        "reason": (f"You to {name}: “{conversation.clean(text)}”  " if text.strip() else "") + f"{name}: “{line}”",
        "event_id": event_id,
        "walk": walk,
    }
    return {
        "npc_id": npc_id,
        "walk": walk,
        "learned": learned,
        "journal_entry": entry,
        "regard_change": change,
        "agreements": agreements,
        "admission": admission,
        "lent": lent,
        "trades": state.get("trades") or {},
        "sim_time_ms": now + tuning.TALK_SECONDS * 1000,
    }


def _lead(npc: Npc, line: str, event_id: int, kind: str, target: str, lead: str) -> dict:
    """Something the stranger learned from this exchange: a line in their journal's leads."""
    return {"npc_id": npc["id"], "name": npc["name"], "said": line, kind: target, "event_id": event_id, "lead": lead}


def _take_in(
    npc: Npc,
    answers: dict,
    text: str,
    happened: str | None,
    key: str,
    line: str,
    note: str,
    name_given: str,
    now: int,
    event_id: int,
) -> dict:
    """What the exchange does to this person: their view of the stranger, their anger, whether they believe it,
    the words themselves, and their own memory of it. Returns the regard change."""
    my_mind = cast.mind(npc)
    my_mind["met"] = True
    change = update_regard(npc, answers)
    if "anger" in answers:
        top = len(reputation.ANGER_LEVELS) - 1
        my_mind["feelings"]["anger"] = round(min(top, conversation.level(answers, "anger")) / top, 2)
    doubted = "believes" in answers and float(answers["believes"]["noul"]) < 0.5
    history = conversation.turns(npc)
    history += [
        {"who": "stranger", "text": conversation.said_or_did(text, happened), "at": now, "doubted": doubted},
        {"who": "them", "text": line, "at": now, "reply": key},
    ]
    del history[:-TURNS_KEPT]
    _remember_exchange(npc, text, happened, line, note, name_given, doubted, now)
    my_mind["said"] = {"text": line, "at": now, "key": f"{npc['id']}:talk:{event_id}"}
    return change


def _settle_deals(state: State, npc: Npc, answers: dict, line: str, event_id: int, learned: list) -> tuple | None:
    """A deal offered is agreed, or one agreed is done: the reply's reading says so. A deal done is rewarded with
    a job: (what they tell the captain, what the captain remembers)."""
    npc_id, name = npc["id"], npc["name"]
    proposed = conversation.deals(state, npc_id, "proposed")
    accepted = [d for d in conversation.deals(state, npc_id, "accepted") if conversation.deal_possible(state, d)]
    if proposed and conversation.yes(answers, "accepts"):
        proposed[0].update(status="accepted", accepted_event=event_id)
    if not (accepted and conversation.yes(answers, "done", tuning.DONE_YES)):
        return None
    deal = accepted[0]
    deal.update(status="fulfilled", fulfilled_event=event_id)
    deal.setdefault("evidence_event_ids", []).append(event_id)
    if deal["reward"] == "pay":  # Paid in goods (D-59): theirs, now the stranger's.
        paid = [i for i in deal.get("pays", []) if state["objects"].get(i, {}).get("owner_id") == npc_id]
        for thing_id in paid:
            state["objects"][thing_id].update(holder_id="player", owner_id="player")
            state["objects"][thing_id].pop("lent_to", None)
        lead = (
            f"{name} is satisfied: you did what was asked, and {name} paid you {conversation.paid_with(state, paid)}."
        )
        learned.append(_lead(npc, line, event_id, "fulfilled", deal["id"], lead))
        return None
    lead = f"{name} is satisfied: you did what was asked, and {name} will speak for you."
    learned.append(_lead(npc, line, event_id, "fulfilled", deal["id"], lead))
    if deal["reward"] == "hire":
        return (
            "they work for me now, and they'll come in under my trade permit.",
            f"{name} has hired the stranger as a hand for trade in the city, under {name}'s trade permit.",
        )
    return (
        "they did what I asked of them, and did it honestly.",
        f"{name} vouched for the stranger, who had done what {name} asked: {deal['task']}.",
    )


def propose(state: State, npc: Npc, offer_id: str, event_id: int | None, line: str, learned: list, lent: list) -> str:
    """Someone offers one of their deals (their card's offers): a task for a reward, and the things the job needs
    lent (D-55: using them isn't theft). It's a lead in the journal. Returns the deal's id."""
    npc_id, name, objects = npc["id"], npc["name"], state["objects"]
    offer = next(o for o in cast.card(npc).get("offers", []) if o["id"] == offer_id)
    deal_id = f"deal_{event_id if event_id is not None else len(state.setdefault('agreements', {}))}"
    state.setdefault("agreements", {})[deal_id] = {
        "id": deal_id,
        "type": "task_for_reward",
        "template": offer_id,
        "issuer": npc_id,
        "task": offer["task"],
        "check": offer["check"],
        "reward": offer["reward"],
        **({"pays": list(offer["pays"])} if offer.get("pays") else {}),  # Goods it pays in (D-59).
        "status": "proposed",
        "offered_event": event_id,
    }
    loaned = []
    for thing_id in offer.get("lends", []):
        thing = objects.get(thing_id)
        if thing and thing["owner_id"] == npc_id and thing.get("lent_to") != "player":
            thing["lent_to"] = "player"
            lent.append({"id": thing_id, "holder_id": thing["holder_id"]})
            loaned.append(thing["name"])
    use = (
        f" You may use {name}'s {', '.join(loaned[:-1]) + ' and ' + loaned[-1] if len(loaned) > 1 else loaned[0]} for it."
        if loaned
        else ""
    )
    learned.append(_lead(npc, line, event_id, "offer", deal_id, f"{name}'s request: {offer['task']}.{use}"))
    return deal_id


def _hand_over(
    state: State, npc: Npc, act: str, target: str | None, line: str, event_id: int, learned: list, lent: list
) -> dict | None:
    """What this person offers, tells or hands over (a deal, a fact, a loan, a gift, a trade, a name), or their
    word at the gate. Returns the admission, if they let the stranger in."""
    npc_id, name, objects = npc["id"], npc["name"], state["objects"]
    if act == "offer":
        propose(state, npc, target, event_id, line, learned, lent)
    elif act == "admit":
        because = [
            m["summary"]
            for m in cast.mind(npc)["memories"]
            if m["kind"] in ("vouch", "demonstration", "gift") and m.get("clarity") != "vague" and m.get("works", True)
        ]
        admission = {"by": npc_id, "event_id": event_id, "because": because[-4:]}
        state.update(admitted=admission, gate_open=True)
        return admission
    elif act == "share":
        cast.mind(npc).setdefault("shared", []).append(target)
        fact = conversation.knowledge(npc)[target]
        learned.append(_lead(npc, line, event_id, "fact", target, fact.get("lead") or fact["text"]))
    elif act == "lend":
        thing = objects[target]
        thing["lent_to"] = "player"
        if thing["holder_id"] == npc_id:
            thing["holder_id"] = "player"  # Handed over.
        lent.append({"id": target, "holder_id": thing["holder_id"]})
        learned.append(_lead(npc, line, event_id, "lend", target, f"{name} lent you their {thing['name']}."))
    elif act == "give":
        thing = objects[target]
        thing.update(holder_id="player", owner_id="player")
        lent.append({"id": target, "holder_id": "player", "owner_id": "player"})
        learned.append(_lead(npc, line, event_id, "gift", target, f"{name} gave you their {thing['name']}."))
    elif act == "accept_trade":
        trade = state["trades"][target]
        for item_id in trade["give_ids"]:
            objects[item_id].update(holder_id=npc_id, owner_id=npc_id)
            lent.append({"id": item_id, "holder_id": npc_id, "owner_id": npc_id})
        for item_id in trade["want_ids"]:
            objects[item_id].update(holder_id="player", owner_id="player")
            lent.append({"id": item_id, "holder_id": "player", "owner_id": "player"})
        trade.update(status="accepted", accepted_event=event_id)
        lead = f"You traded your {' and '.join(trade['give_names'])} for {name}'s {' and '.join(trade['want_names'])}."
        learned.append(_lead(npc, line, event_id, "trade", target, lead))
    elif act == "refer":
        cast.mind(npc).setdefault("referred", []).append(target)
        other = cast.find(state["npcs"], target)
        lead = f"{name} suggested you talk to {other['name']}, the {cast.card(other)['role']}."
        learned.append(_lead(npc, line, event_id, "refer", target, lead))
    return None


def _then(
    state: State,
    npc: Npc,
    act: str,
    target: str | None,
    task: tuple | None,
    fighting: bool,
    line: str,
    event_id: int,
    now: int,
    learned: list,
    lent: list,
) -> None:
    """What this person does once they've spoken: go on an errand, stop fighting, see to their own wound, forgive,
    take back what's theirs, go for a guard, or stay and keep an eye on the stranger. An arrest or an attack is
    carried out by the round (rounds.py); someone fighting fights on."""
    npc_id, name = npc["id"], npc["name"]
    if act == "go_tell":
        other, words = task
        cast.set_job(
            npc, {"kind": "tell", "target": other["id"], "speed": "walk", "message": words, "event": event_id}, now
        )
        learned.append(
            _lead(npc, line, event_id, "errand", other["id"], f"{name} went to tell {other['name']}: {words}")
        )
    elif act == "stop_fighting":
        combat.withdraw(state, npc_id, now)
    elif act == "stand_aside":
        encounter.stand_aside(state, npc, now)
    elif act == "treat_self":
        remedy = state["objects"][target]
        index = next((i for obj, i in conversation.self_remedies(state, npc) if obj["id"] == target), None)
        result = gear.treat(npc, index, remedy, now) if index is not None else {"ok": False}
        if result.get("ok") and result.get("consumed"):
            state["objects"][target] = {**remedy, "holder_id": "used", "condition": "used up"}
            lent.append({"id": target, "holder_id": "used", "owner_id": remedy.get("owner_id")})
        cast.watch(npc, now, tuning.TALK_WATCH_MS)
    elif act == "forgive":
        reputation.settle(state, f"forgiven by {name}", kinds=("theft", "violence", "trouble"), npc_ids={npc_id})
        if fighting:
            combat.withdraw(state, npc_id, now)
        else:
            cast.watch(npc, now, tuning.TALK_WATCH_MS)
    elif act == "take_back":  # Out of the stranger's hands.
        thing = state["objects"][target]
        reputation.settle(state, "taken back", item=thing["name"])
        thing.update(holder_id=npc_id)  # The owner has it back; a guard holds it for them.
        lent.append({"id": target, "holder_id": npc_id, "owner_id": thing["owner_id"]})
        cast.watch(npc, now, tuning.TALK_WATCH_MS)
    elif act in ("seize", "attack", "rob") or fighting:
        pass
    elif act == "call_guard":
        reputation.remember(
            npc,
            {
                "kind": "trouble",
                "severity": 1,
                "victim": npc_id,
                "item": None,
                "event": event_id,
                "clarity": "clear",
                "source": "victim",
                "at": now,
                "summary": f"The stranger was pestering {name} and would not leave them be.",
                "short": f"was pestering {name}",
            },
        )
        cast.set_job(npc, {"kind": "report", "target": target, "speed": "walk", "line": None, "line_id": None}, now)
    else:
        cast.watch(npc, now, tuning.TALK_WATCH_MS)


def _overheard(state: State, npc: Npc, text: str, line: str, event_id: int, now: int) -> None:
    """People close by overhear; they remember it but don't stop to think."""
    name = npc["name"]
    for other in state["npcs"]:
        if (
            other["id"] == npc["id"]
            or not other.get("alive", True)
            or cast.distance(other, state["player"]) > tuning.HEAR_TALK_CELLS
        ):
            continue
        reputation.remember(
            other,
            {
                "kind": "talk",
                "severity": 0,
                "victim": None,
                "item": None,
                "event": event_id,
                "clarity": "heard",
                "source": "overheard",
                "at": now,
                "summary": (
                    f"Overheard the stranger say to {name}: “{conversation.clean(text)}”, and {name} reply: “{line}”"
                )
                if text.strip()
                else f"Overheard {name} say: “{line}”",
                "short": f"was talking with {name}",
            },
        )
