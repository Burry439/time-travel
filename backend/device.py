"""The device from the future (D-50, D-55): what it says, remembers and is told when asked. In a basic training
level it guides the story (its cards and how-to hints); in the main game and the advanced levels it coaches from
what the stranger knows. It never knows anyone's secrets, a level's intended answers, or anything the stranger
hasn't seen (D-59: it once told the user that Sefa needed fire for her lamp, which nobody had told them)."""

from __future__ import annotations

import math

import cast
import content
import gatekeeping
import gear
import reputation
import rules
import stories
import tuning
from shapes import Deal, State


def says(state: State, text: str, kind: str, question: str | None = None) -> None:
    entry = {"at": state.get("sim_time_ms", 0), "text": text, "kind": kind}
    if question:
        entry["question"] = question
    state.setdefault("device_log", []).append(entry)
    state["device_log"] = state["device_log"][-DEVICE_LOG_KEPT:]  # Its memory of you (D-55): long, not the last few.
    state.setdefault("journal", []).append(
        {"kind": "device", "category": kind, "reason": text, **({"question": question} if question else {})}
    )


DEVICE_LOG_KEPT = 400


CONVERSATION_KEPT = 16  # Exchanges the device is given word for word; older questions are listed.


CONTROLS = (
    "Move: WASD or arrows, Shift to run. Hover to see what things are; right-click to look closer. "
    "Left-click to talk to someone or pick something up. T (or Enter) to say or do anything in your own "
    "words. E acts on the nearest thing. I: Pack & gear (hold, wear, treat wounds). J: the journal. "
    "Space: right hand; F: left hand (hold F to raise a shield); X swaps hands; Q throws. Esc: walk away "
    "or the menu. H: ask the device."
)


def moment_detail(state: State, moment: str) -> str | None:
    """What just happened that's worth a word from the device, in words, from the world itself (never from the
    client's text). None when there's nothing to say about it."""
    if moment == "new_lead":
        leads = [e for e in state.get("learned", []) if e.get("lead")]
        return f"The stranger just learned: {leads[-1]['lead']}" if leads else None
    if moment == "failure":
        tried = [e for e in state.get("journal", []) if e.get("kind") == "craft"]
        if tried and tried[-1].get("category") in ("failed", "blocked", "unsupported", "unresolved"):
            return f"An attempt just failed. Tried: “{tried[-1].get('text', '')}”. Why: {tried[-1].get('reason', '')}"
        return None
    if moment == "angry":
        angry = [
            n["name"]
            for n in state["npcs"]
            if n.get("alive", True) and ((n.get("mind") or {}).get("feelings") or {}).get("anger", 0.0) >= 0.67
        ]
        return f"{', '.join(angry)} {'is' if len(angry) == 1 else 'are'} angry with the stranger." if angry else None
    if moment == "news":
        going = [
            (n, cast.find(state["npcs"], n["mind"]["job"].get("target") or ""))
            for n in state["npcs"]
            if ((n.get("mind") or {}).get("job") or {}).get("kind") == "tell"
        ]
        going = [(n, other) for n, other in going if other]
        return (
            f"{going[0][0]['name']} has gone to tell {going[0][1]['name']} something about the stranger."
            if going
            else None
        )
    if moment == "stuck":
        return "The stranger hasn't made any progress for a few minutes."
    return None


def moment_allowed(state: State) -> bool:
    """Not too often, and never over a fight or someone face to face."""
    if state.get("fight") or (state.get("encounter") or {}).get("participants"):
        return False
    remarks = [e for e in state.get("device_log", []) if e.get("kind") == "remark"]
    return not remarks or state.get("sim_time_ms", 0) - remarks[-1].get("at", 0) >= tuning.MOMENT_GAP_MS


def _place_name(state: State) -> str:
    here = cast.player_cell(state)
    places = list(content.map_of(state)["places"].values())
    nearest = min(places, key=lambda place: math.dist(here, tuple(place["cell"])), default=None)
    return nearest["name"] if nearest else "the road"


def _their_part(state: State, deal: Deal) -> str:
    """What the other side of a deal promised, and whether they've done it yet, so the device never runs ahead."""
    issuer = deal.get("issuer") or ""
    decider = gatekeeping.words(state)["decider"]
    promise = (
        "take you on as a hired hand under their trade permit"
        if deal.get("reward") == "hire"
        else f"speak for you to {decider}"
    )
    if deal.get("status") != "fulfilled":
        return f"will {promise} once it's done (not yet)"
    spoke = any(
        m.get("kind") == "vouch" and m.get("by") == issuer
        for n in state["npcs"]
        for m in (n.get("mind") or {}).get("memories", [])
    )
    job = ((cast.find(state["npcs"], issuer) or {}).get("mind") or {}).get("job") or {}
    return (
        f"has done it: spoke for you to {decider}"
        if spoke
        else f"is on the way to {promise} now"
        if job.get("kind") == "vouch"
        else f"promised to {promise}"
    )


def _coach(state: State) -> dict:
    """The main game: what a coach needs, all of it things the stranger knows (D-55)."""
    leads, seen_leads = [], set()
    for entry in reversed(state.get("learned", [])):
        lead = entry.get("lead")
        if lead and lead not in seen_leads:
            seen_leads.add(lead)
            leads.append({"lead": lead, "from": entry.get("name", "")})
    people = [
        {
            "name": n["name"],
            "role": cast.card(n).get("role", ""),
            "stands": reputation.STANDING_WORDS[reputation.standing(n)],
        }
        for n in state["npcs"]
        if (n.get("mind") or {}).get("met") or (n.get("mind") or {}).get("memories")
    ]
    deals = [
        {
            "with": (cast.find(state["npcs"], a.get("issuer") or "") or {}).get("name", "?"),
            "task": a.get("task", ""),
            "status": {"proposed": "offered", "accepted": "agreed, not yet done", "fulfilled": "done"}.get(
                a.get("status"), a.get("status")
            ),
            "their_part": _their_part(state, a),
        }
        for a in (state.get("agreements") or {}).values()
        if a.get("type") == "task_for_reward"
    ]
    made = [o["name"] for o in state["objects"].values() if o.get("created_by") == "player"][-10:]
    lent = [
        f"{(cast.find(state['npcs'], o.get('owner_id') or '') or {}).get('name', 'someone')}'s {o['name']}"
        for o in state["objects"].values()
        if o.get("lent_to") == "player"
    ]
    quests = [  # The quests the stranger has come into: only what they've reached and been told (D-70).
        {
            "quest": story["title"],
            "what_you_know": [s["text"] for s in story["steps"]][-4:],
            "open_leads": [state["learned"][i]["lead"] for i in story["threads"] if state["learned"][i].get("lead")],
        }
        for story in (stories.page(state) or [])
    ][:6]
    return {
        "leads_newest_first": leads[:12],
        "quests": quests,
        "people_met": people,
        "deals": deals,
        "things_you_made": made,
        "lent_to_you": lent,
        "where_you_are": _place_name(state),
        "city": (
            gatekeeping.words(state)["arrived"]
            if state.get("inside_city")
            else gatekeeping.words(state)["let_in"]
            if state.get("admitted")
            else "not let in yet"
        ),
    }


def context(state: State, question: str, moment: str | None = None) -> dict:
    """What the device can know: what the stranger carries, wears and has seen, what they tried, the story step
    (with its written hints as guidance), and the controls. Never anyone's secrets or anything unseen. It also
    remembers what the two of them have said (D-55), and in the main game it has what a coach needs."""
    here = cast.player_cell(state)
    player = state["player"]
    in_sight = [n for n in state["npcs"] if cast.distance(n, here) <= tuning.SIGHT_CELLS]
    things = [
        o
        for o in state["objects"].values()
        if o.get("holder_id") is None and "carry" in o["capabilities"] and cast.distance(o, here) <= tuning.SIGHT_CELLS
    ]
    attempts = [e for e in state.get("journal", []) if e.get("kind") == "craft"][-3:]
    current = guided_step(state)
    log = state.get("device_log", [])
    talked = [e for e in log if e.get("question") or e.get("kind") in ("answer", "remark")]
    conversation = [
        {"you_asked": e["question"], "i_said": e["text"]} if e.get("question") else {"i_said": e["text"]}
        for e in talked[-CONVERSATION_KEPT:]
    ]
    earlier = [e["question"] for e in talked[:-CONVERSATION_KEPT] if e.get("question")][-20:]
    return {
        "question": question,
        **({"moment": moment_detail(state, moment)} if moment else {}),
        "our_conversation": conversation,
        "earlier_questions": earlier,
        **({} if current else _coach(state)),
        "tutorial": bool(current),
        "step": {
            "title": current["title"],
            "objective": current.get("task", ""),
            "hints_you_may_give": current.get("help", []),
            **({"words_suggested": current["suggest"]["text"]} if current.get("suggest") else {}),
        }
        if current
        else None,
        "goal": content.level(state).get("goal") or state.get("objective", ""),
        "you_carry": [{"name": o["name"], "what_it_is": gear.words(o)} for o in rules.carried(state)],
        "you_wear": sorted(
            {
                state["objects"][oid]["name"]
                for slot, oid in (player.get("equipped") or {}).items()
                if slot in gear.COVERS and oid in state["objects"]
            }
        ),
        "your_health": round(float(player.get("health", 100))),
        "your_wounds": [gear.describe(c) for c in player.get("conditions", []) if c["kind"] != "knocked_out"],
        "people_in_sight": [
            {
                "name": n["name"],
                "role": cast.card(n).get("role", ""),
                "state": "dead"
                if not n.get("alive", True)
                else "down"
                if n.get("down")
                else "hurt"
                if n.get("health", 100) < 100
                else "well",
            }
            for n in in_sight
        ],
        "things_in_sight": [o["name"] for o in things][:20],
        "recent_attempts": [
            {"tried": e.get("text", ""), "result": e.get("category", ""), "why": e.get("reason", "")[:200]}
            for e in attempts
        ],
        "controls": CONTROLS,
        # The same facts the judge rules by (D-72: the device once advised striking flint on iron, which the judge
        # then refused, because it had only its own knowledge).
        "how_things_work_here": content.MATERIALS["material_facts"],
    }


def guided_step(state: State) -> dict | None:
    """The step a basic level is guiding the stranger through, with its how-to hints. An advanced level has a goal
    and no answers to give: there the device coaches from what the stranger knows, as in the main game."""
    current = rules.scene_step(state)
    return current if current and content.level(state).get("track") != "advanced" else None


def fallback_answer(state: State) -> str:
    """When the model can't be asked: the current step's first hint, or the controls."""
    current = guided_step(state)
    if current and current.get("help"):
        return current["help"][0]
    return "I can't reach far right now. Look around, talk to people, and try what you know. H asks me again."
