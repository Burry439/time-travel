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
import rules
import stories
import tuning
from shapes import Deal, Npc, State

MAX_TEXT = 300


BUSY = {
    "attack": "{name} is attacking you, not talking.",
    "flee": "{name} is running away from you.",
    "report": "{name} is hurrying off somewhere and won't stop.",
}


REWARDS = {
    "vouch": "{name} will be grateful and put in a good word for the stranger with {decider}",
    "hire": "{name} will take the stranger on as a hired hand for trade in the city, under {name}'s own permit",
    "pay": "{name} will give the stranger {pays}",  # Goods for work (D-59): the things named on the offer.
}


def paid_with(state: State, thing_ids: list[str]) -> str:
    """What a deal pays, in words: "a small sack of flour and a loaf"."""
    names = [f"a {state['objects'][i]['name']}" for i in thing_ids if i in state.get("objects", {})]
    return " and ".join(names) or "something of theirs"


def clean(text: str) -> str:
    """The player's words as quoted speech: one line, no quote marks to break out of, bounded."""
    text = " ".join(str(text).split()).replace("“", "'").replace("”", "'").replace('"', "'")
    return text[:MAX_TEXT]


def knowledge(npc: Npc) -> dict[str, dict]:
    return cast.card(npc).get("knowledge", {})


def turns(npc: Npc) -> list[dict]:
    return cast.mind(npc).setdefault("talk", [])


def busy(npc: Npc) -> str | None:
    """Why this person can't talk right now, if they can't."""
    if not npc.get("alive", True):
        return f"{npc['name']} is dead."
    job = (npc.get("mind") or {}).get("job")
    if job and job["kind"] in BUSY:
        return BUSY[job["kind"]].format(name=npc["name"])
    return None


def walk_to(state: State, npc: Npc) -> list[list[int]] | None:
    """Cells to walk before talking ([] if already close enough); None if they can't be reached."""
    if cast.distance(state["player"], npc) <= tuning.TALK_CELLS:
        return []
    return paths.plan_walk(state, [cast.cell(npc)])


def standing_at(state: State, walk: list[list[int]]) -> dict:
    """A copy of the world with the player where the walk ends: what the person sees while talking."""
    draft = copy.deepcopy(state)
    if walk:
        draft["player"].update(x=walk[-1][0], y=walk[-1][1])
    return draft


def nearest_guard(state: State, npc: Npc) -> dict | None:
    guards = [g for g in state["npcs"] if g["id"] != npc["id"] and g.get("alive", True) and cast.card(g).get("guard")]
    return min(guards, key=lambda g: cast.distance(g, npc), default=None)


def deals(state: State, npc_id: str, *statuses: str) -> list[dict]:
    """This person's deals with the stranger in these states, oldest first."""
    return sorted(
        (a for a in state.get("agreements", {}).values() if a.get("issuer") == npc_id and a.get("status") in statuses),
        key=lambda a: a["id"],
    )


def stolen_in_view(state: State, npc: Npc) -> list[dict]:
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


def open_trades(state: State, npc: Npc) -> list[dict]:
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


def deal_possible(state: State, deal: Deal) -> bool:
    """A deal with a world condition (the beam in its brackets) can only be done once that holds."""
    return deal.get("type") != "negotiated" and rules.holds(state, cast.offer_of(state, deal).get("done_when"))


def lendable(state: State, npc: Npc) -> list[dict]:
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


def helped_by_stranger(npc: Npc) -> bool:
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


def holding(state: State, person_id: str) -> list[dict]:
    """What someone has on them or in their hands (not what they wear)."""
    person = state["player"] if person_id == "player" else cast.find(state["npcs"], person_id) or {}
    worn = {oid for slot, oid in (person.get("equipped") or {}).items() if slot in gear.COVERS}
    return [o for o in state["objects"].values() if o.get("holder_id") == person_id and o["id"] not in worn]


def self_remedies(state: State, npc: Npc) -> list[tuple[dict, int]]:
    """Remedies this person holds that treat one of their own untreated wounds: [(remedy, condition index)]."""
    found = []
    for obj in holding(state, npc["id"]):
        spec = gear.remedy_for(obj)
        for index, condition in enumerate(npc.get("conditions") or []):
            if spec and spec["treats"].get(condition["kind"]) and condition in gear.untreated(npc):
                found.append((obj, index))
                break
    return found


def replies(state: State, npc: Npc) -> dict[str, dict]:
    """Every reply code can carry out for this person now: {key: {act, target, description}}. In the order the
    voice sees them: talking, what they have to offer, wrongs to put right, going to do something, and parting."""
    options: dict[str, dict] = {}
    for group in (_talking, _offering, _wrongs, _robbing, _going, _parting):
        group(state, npc, options)
    withheld = rules.role(state, npc).get("withholds", [])  # Kade in the middle of his lessons stays put (D-57).
    return {k: o for k, o in options.items() if o["act"] not in withheld} if withheld else options


def _option(act: str, description: str, target: str | None = None) -> dict:
    return {"act": act, "target": target, "description": description}


def _talking(state: State, npc: Npc, options: dict) -> None:
    """Just talking, asking back, telling what they know, and sending the stranger to someone else."""
    name, me, my_mind = npc["name"], cast.card(npc), cast.mind(npc)
    options["answer"] = _option(
        "answer",
        f"{name} just talks: answers, reacts, explains, gives directions around town or "
        f"says what they think, without doing anything else.",
    )
    recent = [t for t in turns(npc) if t["who"] == "them"][-3:]
    if not any(t.get("reply") == "ask_back" for t in recent):  # Asked once and answered: the conversation moves on.
        options["ask_back"] = _option(
            "ask_back",
            f"{name} asks the stranger a question of their own: who they are, what they want, or what they meant.",
        )
    for fact_id, fact in knowledge(npc).items():
        if fact_id in my_mind.get("shared", []):
            continue
        options[f"share:{fact_id}"] = _option("share", f"{name} tells the stranger: {fact['text']}", fact_id)
    for secret in stories.confidable(state, npc):  # Code says they could; whether they do is theirs (D-61).
        options[f"confide:{secret['id']}"] = _option(
            "confide", f"{name} confides in the stranger, privately: {secret['text']}", secret["id"]
        )
    for other_id in me.get("refers", []):
        other = cast.find(state["npcs"], other_id)
        if other is None or not other.get("alive", True) or other_id in my_mind.get("referred", []):
            continue
        who = cast.relation(npc, other_id) or f"{other['name']} the {cast.card(other)['role']}"
        steps = round(cast.distance(other, npc))
        options[f"refer:{other_id}"] = _option(
            "refer", f"{name} suggests the stranger go and talk to {who} (about {steps} steps from here).", other_id
        )


def _offering(state: State, npc: Npc, options: dict) -> None:
    """A deal from their authored offers, a loan or a gift of their own things, a trade the stranger proposed."""
    name, me = npc["name"], cast.card(npc)
    offered = {a.get("template") for a in state.get("agreements", {}).values() if a.get("issuer") == npc["id"]}
    for offer in me.get("offers", []):
        if offer["id"] not in offered:
            reward = REWARDS[offer["reward"]].format(
                name=name, pays=paid_with(state, offer.get("pays", [])), decider=gatekeeping.words(state)["decider"]
            )
            options[f"offer:{offer['id']}"] = _option(
                "offer", f"{name} proposes a deal: if the stranger will {offer['task']}, {reward}.", offer["id"]
            )
    for obj in lendable(state, npc):
        options[f"lend:{obj['id']}"] = _option(
            "lend", f"{name} lets the stranger take and use their {obj['name']}.", obj["id"]
        )
    if not npc.get("down"):
        for obj in lendable(state, npc)[:3]:
            options[f"give:{obj['id']}"] = _option(
                "give", f"{name} gives the stranger their {obj['name']} to keep.", obj["id"]
            )
    for move in stories.moves_for(state, npc):  # Something they could now agree to (D-61): theirs to decide.
        options[f"story:{move['id']}"] = _option(
            "story", f"{move['description']} (You'd agree {move['would_agree_if']}.)", move["id"]
        )
    for trade in open_trades(state, npc):
        options[f"accept_trade:{trade['id']}"] = _option(
            "accept_trade",
            f"{name} accepts the stranger's trade: their {' and '.join(trade['give_names'])} for "
            f"{name}'s {' and '.join(trade['want_names'])}.",
            trade["id"],
        )


def _wrongs(state: State, npc: Npc, options: dict) -> None:
    """Stolen things demanded or taken back; a crime not put right forgiven, or answered with an arrest or a fight
    (only a real crime, D-46)."""
    name, me = npc["name"], cast.card(npc)
    here = cast.distance(npc, state["player"])
    for obj in stolen_in_view(state, npc):  # Their things, or (for a guard) things they know were stolen.
        owner = "their" if obj["owner_id"] == npc["id"] else f"{cast.find(state['npcs'], obj['owner_id'])['name']}'s"
        options[f"demand:{obj['id']}"] = _option(
            "demand", f"{name} demands the stranger hand back {owner} {obj['name']}.", obj["id"]
        )
        if here <= tuning.REACH_TAKE:
            options[f"take_back:{obj['id']}"] = _option(
                "take_back", f"{name} takes {owner} {obj['name']} back out of the stranger's hands.", obj["id"]
            )
    crime = reputation.unresolved_crime(npc)
    if crime is None:
        return
    if not me.get("guard") and crime.get("victim") == npc["id"]:
        options["forgive"] = _option("forgive", f"{name} lets it go: {crime['short']} is put behind them.")
    elif me.get("guard"):
        options["forgive"] = _option("forgive", f"{name} lets the matter drop ({crime['short']}): it's been put right.")
    alive = state["player"].get("alive", True)
    if me.get("guard") and here <= tuning.REACH_TAKE and alive:
        options["seize"] = _option(
            "seize",
            f"{name} arrests the stranger: anything stolen goes back, and the stranger is "
            f"marched off down the south road and kept from the gate for a while.",
        )
    armed = cast.armed_with(state, npc)
    if alive and (me.get("guard") or armed) and npc["id"] not in ((state.get("fight") or {}).get("attackers") or []):
        options["attack"] = _option(
            "attack",
            f"{name} attacks the stranger "
            + (
                f"to kill, with their {armed or 'fists'}."
                if reputation.knows_a_crime(npc)
                else f"to beat them into submission{' and arrest them' if me.get('guard') else ''}, not to kill."
            ),
        )


def _robbing(state: State, npc: Npc, options: dict) -> None:
    """A robber holding the stranger up (D-59): take what they're after by force, or stand aside (paid, talked
    round, or not worth the fight)."""
    if not cast.robbing(npc):
        return
    name, wants = npc["name"], cast.card(npc)["robs"]
    fighting = npc["id"] in ((state.get("fight") or {}).get("attackers") or [])
    if not fighting and state["player"].get("alive", True):
        options["rob"] = _option(
            "rob", f"{name} comes at the stranger to beat them down and take {wants}, not to kill."
        )
    options["stand_aside"] = _option(
        "stand_aside",
        f"{name} stands aside and lets the stranger go on their way: paid, talked round, or not worth it.",
    )


def _going(state: State, npc: Npc, options: dict) -> None:
    """Going to do something for the stranger: speak for them, carry word, stop fighting, see to their own wound,
    let them in."""
    name, my_mind = npc["name"], cast.mind(npc)
    captain = cast.captain(state)
    fighting = npc["id"] in ((state.get("fight") or {}).get("attackers") or [])
    if (
        captain
        and npc["id"] != captain["id"]
        and captain.get("alive", True)
        and not my_mind.get("vouched")
        and not fighting
    ):
        options["vouch"] = _option(
            "vouch", f"{name} goes to {gatekeeping.decider_called(state, captain)} now and speaks for the stranger."
        )
    if not fighting and not npc.get("down"):
        options["go_tell"] = _option(
            "go_tell",
            f"{name} goes off now to find someone in town and tell them something "
            f"(who: errand_to; what: errand_message). Choose this whenever {name} "
            f"says they'll go and tell or ask someone.",
        )
    if fighting:
        options["stop_fighting"] = _option("stop_fighting", f"{name} stops attacking the stranger and backs off.")
    for obj, index in self_remedies(state, npc):  # Something they were given for their own wound (D-53).
        options[f"treat_self:{obj['id']}"] = _option(
            "treat_self",
            f"{name} puts the {obj['name']} on their own "
            f"{gear.describe(npc['conditions'][index]).removeprefix('the ')}.",
            obj["id"],
        )
    if gatekeeping.can_admit(state, npc):
        entry = gatekeeping.words(state)
        options["admit"] = _option(
            "admit",
            f"{name} {entry['admit']}." if npc["id"] == cast.captain_id(state) else f"{name} {entry['let_through']}.",
        )


def _parting(state: State, npc: Npc, options: dict) -> None:
    """Refusing, sending the stranger away, fetching a guard, or simply ending it."""
    name = npc["name"]
    options["refuse"] = _option("refuse", f"{name} refuses what the stranger is asking for.")
    options["tell_to_leave"] = _option("tell_to_leave", f"{name} tells the stranger to go away and leave them be.")
    guard = None if cast.card(npc).get("guard") else nearest_guard(state, npc)
    if guard is not None:
        options[f"call_guard:{guard['id']}"] = _option(
            "call_guard",
            f"{name} breaks off and goes to fetch {guard['name']} the guard about the stranger.",
            guard["id"],
        )
    options["end"] = _option("end", f"{name} politely ends the conversation.")


def said_or_did(text: str, happened: str | None) -> str:
    """How the stranger's part of an exchange is remembered: their words, or what they did instead."""
    return clean(text) if text.strip() else f"({clean(happened or 'says nothing')})"


def admits_now(state: State, npc: Npc, answers: dict) -> bool:
    """A guard's own rule met, by the reply's reading: reason enough and no threat (GDD 4.3, D-43), with real
    grounds in what they hold, so a claim ("Hessa has spoken for me") never opens the gate by itself (D-55)."""
    return (
        "admit" in replies(state, npc)
        and yes(answers, "reason", tuning.REASON_YES)
        and gatekeeping.grounds_to_admit(npc)
    )


def moves(state: State, npc: Npc, answers: dict | None = None) -> dict[str, str]:
    """The moves the voice may pick from: every legal reply. Letting the stranger in is offered to a guard who
    could; code then checks the same reply's own reading (reason enough, no threat) before the gate opens (D-46)."""
    options = {k: o["description"] for k, o in replies(state, npc).items()}
    if "admit" in options and not gatekeeping.grounds_to_admit(npc):
        del options["admit"]  # Nothing real to go on yet (D-55): the voice isn't offered a yes that code would refuse.
    return options


def decided_reply(state: State, npc: Npc, answers: dict, proposed: str) -> str:
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
