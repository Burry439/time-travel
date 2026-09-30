"""A conversation's ground rules: who can talk now and from where, what they know and have said, their deals
with the stranger, and every move code can carry out for them this exchange (tell, send, offer, lend, give,
demand back, take back, arrest, attack, fetch a guard, refuse, let in, part). The voice picks among these."""

from __future__ import annotations

import copy

import cast
import gatekeeping
import gear
import paths
import reputation
import tuning

MAX_TEXT = 300


BUSY = {
    "attack": "{name} is attacking you, not talking.",
    "flee": "{name} is running away from you.",
    "report": "{name} is hurrying off somewhere and won't stop.",
}


REWARDS = {
    "vouch": "{name} will be grateful and put in a good word for the stranger with the captain",
    "hire": "{name} will take the stranger on as a hired hand for trade in the city, under {name}'s own permit",
}


def clean(text: str) -> str:
    """The player's words as quoted speech: one line, no quote marks to break out of, bounded."""
    text = " ".join(str(text).split()).replace("“", "'").replace("”", "'").replace('"', "'")
    return text[:MAX_TEXT]


def knowledge(npc: dict) -> dict[str, dict]:
    return cast.card(npc).get("knowledge", {})


def turns(npc: dict) -> list[dict]:
    return cast.mind(npc).setdefault("talk", [])


def busy(npc: dict) -> str | None:
    """Why this person can't talk right now, if they can't."""
    if not npc.get("alive", True):
        return f"{npc['name']} is dead."
    job = (npc.get("mind") or {}).get("job")
    if job and job["kind"] in BUSY:
        return BUSY[job["kind"]].format(name=npc["name"])
    return None


def walk_to(state: dict, npc: dict) -> list[list[int]] | None:
    """Cells to walk before talking ([] if already close enough); None if they can't be reached."""
    if cast.distance(state["player"], npc) <= tuning.TALK_CELLS:
        return []
    return paths.plan_walk(state, [cast.cell(npc)])


def standing_at(state: dict, walk: list[list[int]]) -> dict:
    """A copy of the world with the player where the walk ends: what the person sees while talking."""
    draft = copy.deepcopy(state)
    if walk:
        draft["player"].update(x=walk[-1][0], y=walk[-1][1])
    return draft


def nearest_guard(state: dict, npc: dict) -> dict | None:
    guards = [g for g in state["npcs"] if g["id"] != npc["id"] and g.get("alive", True) and cast.card(g).get("guard")]
    return min(guards, key=lambda g: cast.distance(g, npc), default=None)


def deals(state: dict, npc_id: str, *statuses: str) -> list[dict]:
    """This person's deals with the stranger in these states, oldest first."""
    return sorted(
        (a for a in state.get("agreements", {}).values() if a.get("issuer") == npc_id and a.get("status") in statuses),
        key=lambda a: a["id"],
    )


def stolen_in_view(state: dict, npc: dict) -> list[dict]:
    """Things the stranger is carrying that belong to this person, or, for a guard, that they know were stolen."""
    known = {
        m.get("item")
        for m in cast.mind(npc)["memories"]
        if m["kind"] == "theft" and not m.get("doubted") and not m.get("settled")
    }
    guard = cast.card(npc).get("guard")
    return [
        o
        for o in state["objects"].values()
        if o["holder_id"] == "player"
        and o.get("owner_id") not in (None, "player")
        and o.get("lent_to") != "player"
        and (o["owner_id"] == npc["id"] or (guard and o["name"] in known))
    ]


def open_trades(state: dict, npc: dict) -> list[dict]:
    """Trades the stranger has offered this person that could still happen."""
    objects = state["objects"]
    return [
        t
        for t in (state.get("trades") or {}).values()
        if t["recipient_id"] == npc["id"]
        and t["status"] == "offered"
        and all(objects[i]["holder_id"] == "player" for i in t["give_ids"])
        and all(
            objects[i]["owner_id"] == npc["id"] and objects[i]["holder_id"] in (None, npc["id"]) for i in t["want_ids"]
        )
    ]


def deal_possible(state: dict, deal: dict) -> bool:
    """A deal with a world condition (the beam in its brackets) can only be done once that holds."""
    offer = next(
        (
            o
            for o in cast.card(cast.find(state["npcs"], deal["issuer"])).get("offers", [])
            if o["id"] == deal.get("template")
        ),
        {},
    )
    placed = (offer.get("done_when") or {}).get("installed")
    return not placed or bool(state["objects"].get(placed, {}).get("installed_in"))


def lendable(state: dict, npc: dict) -> list[dict]:
    """Things of this person's the stranger could be allowed to use (at most four, nearest first)."""
    things = [
        o
        for o in state["objects"].values()
        if o["owner_id"] == npc["id"]
        and o.get("lent_to") != "player"
        and o["holder_id"] in (None, npc["id"])
        and "carry" in o["capabilities"]
        and o["condition"] == "usable"
    ]
    return sorted(things, key=lambda o: (cast.distance((o["x"], o["y"]), npc), o["id"]))[:4]


def helped_by_stranger(npc: dict) -> bool:
    """The stranger has done this person (or their family) a real kindness they saw or felt: a wound treated,
    a gift. Reason enough to speak up for them, whatever words were said (D-51)."""
    family = {npc["id"], *cast.card(npc).get("family", [])}
    return any(
        m["kind"] in ("help", "gift") and m.get("victim") in family and m.get("clarity") != "vague"
        for m in cast.mind(npc).get("memories", [])
    )


ERRANDS = (
    "vouch",
    "go_tell",
    "call_guard",
    "refer",
    "lend",
    "give",
    "offer",
    "accept_trade",
    "take_back",
    "seize",
    "attack",
    "admit",
    "stop_fighting",
    "forgive",
    "treat_self",
)  # Moves that carry something out.


def holding(state: dict, person_id: str) -> list[dict]:
    """What someone has on them or in their hands (not what they wear)."""
    person = state["player"] if person_id == "player" else cast.find(state["npcs"], person_id) or {}
    worn = {oid for slot, oid in (person.get("equipped") or {}).items() if slot in gear.COVERS}
    return [o for o in state["objects"].values() if o.get("holder_id") == person_id and o["id"] not in worn]


def self_remedies(state: dict, npc: dict) -> list[tuple[dict, int]]:
    """Remedies this person holds that treat one of their own untreated wounds: [(remedy, condition index)]."""
    found = []
    for obj in holding(state, npc["id"]):
        spec = gear.remedy_for(obj)
        for index, condition in enumerate(npc.get("conditions") or []):
            if spec and spec["treats"].get(condition["kind"]) and condition in gear.untreated(npc):
                found.append((obj, index))
                break
    return found


def replies(state: dict, npc: dict) -> dict[str, dict]:
    """Every reply code can carry out for this person now: {key: {act, target, description}}."""
    name, me, my_mind = npc["name"], cast.card(npc), cast.mind(npc)

    def option(act: str, description: str, target: str | None = None) -> dict:
        return {"act": act, "target": target, "description": description}

    options = {
        "answer": option(
            "answer",
            f"{name} just talks: answers, reacts, explains, gives directions around town or "
            f"says what they think, without doing anything else.",
        ),
    }
    recent = [t for t in turns(npc) if t["who"] == "them"][-3:]
    if not any(t.get("reply") == "ask_back" for t in recent):  # Asked once and answered: the conversation moves on.
        options["ask_back"] = option(
            "ask_back",
            f"{name} asks the stranger a question of their own: who they are, what they want, or what they meant.",
        )
    trust = reputation.regard(npc)["trust"]
    for fact_id, fact in knowledge(npc).items():
        if fact_id in my_mind.get("shared", []) or (fact.get("trusted") and trust < tuning.SHARE_TRUST):
            continue
        options[f"share:{fact_id}"] = option("share", f"{name} tells the stranger: {fact['text']}", fact_id)
    for other_id in me.get("refers", []):
        other = cast.find(state["npcs"], other_id)
        if other is None or not other.get("alive", True) or other_id in my_mind.get("referred", []):
            continue
        who = cast.relation(npc, other_id) or f"{other['name']} the {cast.card(other)['role']}"
        steps = round(cast.distance(other, npc))
        options[f"refer:{other_id}"] = option(
            "refer", f"{name} suggests the stranger go and talk to {who} (about {steps} steps from here).", other_id
        )
    offered = {a.get("template") for a in state.get("agreements", {}).values() if a.get("issuer") == npc["id"]}
    for offer in me.get("offers", []):
        if offer["id"] not in offered:
            reward = REWARDS[offer["reward"]].format(name=name)
            options[f"offer:{offer['id']}"] = option(
                "offer", f"{name} proposes a deal: if the stranger will {offer['task']}, {reward}.", offer["id"]
            )
    for obj in lendable(state, npc):
        options[f"lend:{obj['id']}"] = option(
            "lend", f"{name} lets the stranger take and use their {obj['name']}.", obj["id"]
        )
    if trust >= tuning.GIVE_TRUST:
        for obj in lendable(state, npc)[:3]:
            options[f"give:{obj['id']}"] = option(
                "give", f"{name} gives the stranger their {obj['name']} to keep.", obj["id"]
            )
    for trade in open_trades(state, npc):
        options[f"accept_trade:{trade['id']}"] = option(
            "accept_trade",
            f"{name} accepts the stranger's trade: their {' and '.join(trade['give_names'])} for "
            f"{name}'s {' and '.join(trade['want_names'])}.",
            trade["id"],
        )
    here = cast.distance(npc, state["player"])
    for obj in stolen_in_view(state, npc):  # Their things, or (for a guard) things they know were stolen.
        owner = "their" if obj["owner_id"] == npc["id"] else f"{cast.find(state['npcs'], obj['owner_id'])['name']}'s"
        options[f"demand:{obj['id']}"] = option(
            "demand", f"{name} demands the stranger hand back {owner} {obj['name']}.", obj["id"]
        )
        if here <= tuning.REACH_TAKE:
            options[f"take_back:{obj['id']}"] = option(
                "take_back", f"{name} takes {owner} {obj['name']} back out of the stranger's hands.", obj["id"]
            )
    crime = reputation.unresolved_crime(npc)  # Arrests and attacks only for a real crime not put right (D-46).
    if crime is not None and not me.get("guard") and crime.get("victim") == npc["id"]:
        options["forgive"] = option("forgive", f"{name} lets it go: {crime['short']} is put behind them.")
    elif crime is not None and me.get("guard"):
        options["forgive"] = option("forgive", f"{name} lets the matter drop ({crime['short']}): it's been put right.")
    if crime is not None and me.get("guard") and here <= tuning.REACH_TAKE and state["player"].get("alive", True):
        options["seize"] = option(
            "seize",
            f"{name} arrests the stranger: anything stolen goes back, and the stranger is "
            f"marched off down the south road and kept from the gate for a while.",
        )
    if (
        crime is not None
        and state["player"].get("alive", True)
        and (me.get("guard") or cast.armed_with(state, npc))
        and npc["id"] not in ((state.get("fight") or {}).get("attackers") or [])
    ):
        deadly = reputation.knows_a_crime(npc)
        options["attack"] = option(
            "attack",
            f"{name} attacks the stranger "
            + (
                f"to kill, with their {me.get('weapon') or 'fists'}."
                if deadly
                else f"to beat them into submission{' and arrest them' if me.get('guard') else ''}, not to kill."
            ),
        )
    captain = cast.find(state["npcs"], gatekeeping.CAPTAIN)
    fighting = npc["id"] in ((state.get("fight") or {}).get("attackers") or [])
    if (
        npc["id"] != gatekeeping.CAPTAIN
        and captain
        and captain.get("alive", True)
        and not my_mind.get("vouched")
        and not fighting
        and (trust >= tuning.VOUCH_TRUST or helped_by_stranger(npc))
    ):
        options["vouch"] = option("vouch", f"{name} goes to Captain Roderic now and speaks for the stranger.")
    if not fighting and not npc.get("down"):
        options["go_tell"] = option(
            "go_tell",
            f"{name} goes off now to find someone in town and tell them something "
            f"(who: errand_to; what: errand_message). Choose this whenever {name} "
            f"says they'll go and tell or ask someone.",
        )
    if fighting:
        options["stop_fighting"] = option("stop_fighting", f"{name} stops attacking the stranger and backs off.")
    for obj, index in self_remedies(state, npc):  # Something they were given for their own wound (D-53).
        options[f"treat_self:{obj['id']}"] = option(
            "treat_self",
            f"{name} puts the {obj['name']} on their own "
            f"{gear.describe(npc['conditions'][index]).removeprefix('the ')}.",
            obj["id"],
        )
    if gatekeeping.can_admit(state, npc):
        options["admit"] = option(
            "admit",
            f"{name} admits the stranger into the city and orders the gate opened for them."
            if npc["id"] == gatekeeping.CAPTAIN
            else f"{name} lets the stranger through the gate on their own say-so, and has it opened for them.",
        )
    options["refuse"] = option("refuse", f"{name} refuses what the stranger is asking for.")
    options["tell_to_leave"] = option("tell_to_leave", f"{name} tells the stranger to go away and leave them be.")
    guard = None if me.get("guard") else nearest_guard(state, npc)
    if guard is not None:
        options[f"call_guard:{guard['id']}"] = option(
            "call_guard",
            f"{name} breaks off and goes to fetch {guard['name']} the guard about the stranger.",
            guard["id"],
        )
    options["end"] = option("end", f"{name} politely ends the conversation.")
    import tutorial

    if tutorial.keeps(state, npc):  # Kade in the middle of his lessons stays put (D-57).
        options = {k: o for k, o in options.items() if o["act"] not in ("go_tell", "vouch", "call_guard", "admit")}
    return options


def said_or_did(text: str, happened: str | None) -> str:
    """How the stranger's part of an exchange is remembered: their words, or what they did instead."""
    return clean(text) if text.strip() else f"({clean(happened or 'says nothing')})"


def admits_now(state: dict, npc: dict, answers: dict) -> bool:
    """A guard's own rule met, by the reply's reading: reason enough and no threat (GDD 4.3, D-43), with real
    grounds in what they hold, so a claim ("Hessa has spoken for me") never opens the gate by itself (D-55)."""
    return (
        "admit" in replies(state, npc)
        and yes(answers, "reason", tuning.REASON_YES)
        and "threat" in answers
        and float(answers["threat"].get("noul", 1.0)) < tuning.THREAT_NO
        and gatekeeping.grounds_to_admit(npc)
    )


def moves(state: dict, npc: dict, answers: dict | None = None) -> dict[str, str]:
    """The moves the voice may pick from: every legal reply. Letting the stranger in is offered to a guard who
    could; code then checks the same reply's own reading (reason enough, no threat) before the gate opens (D-46)."""
    options = {k: o["description"] for k, o in replies(state, npc).items()}
    if "admit" in options and not gatekeeping.grounds_to_admit(npc):
        del options["admit"]  # Nothing real to go on yet (D-55): the voice isn't offered a yes that code would refuse.
    return options


def decided_reply(state: dict, npc: dict, answers: dict, proposed: str) -> str:
    """The move code will carry out: the one the voice picked, if it is legal now. Letting the stranger in also
    needs the guard's own rule met by the reading ("reason", "threat"): their authored motive (GDD 4.3, D-43), checked by code; never forced on words that refuse (D-44)."""
    options = replies(state, npc)
    key = proposed if proposed in options else "answer"
    if key == "admit" and not admits_now(state, npc, answers):
        return "answer"
    return key


def level(answers: dict, name: str) -> int:
    score = (answers.get(name) or {}).get("score")
    return 2 if score is None else max(0, min(4, int(round(float(score)))))


def yes(answers: dict, name: str, threshold: float = 0.5) -> bool:
    return name in answers and float(answers[name].get("noul", 0.0)) >= threshold
