"""What each person remembers of the stranger, and what follows from it: their regard (trust, suspicion,
respect, awe), the crimes they hold against them, and the one word the player sees for where they stand
(GDD 7.2, D-46, D-55). Memories change only through events."""

from __future__ import annotations

import cast
import content
import evidence
import tuning
from shapes import Memory, Npc, State

CUES: dict[str, list[str]] = content.LINES["cues"]


FEAR_LEVELS = ["Not afraid", "Uneasy", "Afraid", "Terrified"]


ANGER_LEVELS = ["Calm", "Annoyed", "Angry", "Furious"]


EVIDENCE_KINDS = ("demonstration", "vouch", "help", "gift")  # Good things seen or heard about the stranger.


CRIME_KINDS = ("violence", "theft", "breach")  # breach: unbarring the city gate (D-42).


def knows(npc: Npc, event) -> bool:
    """Fact identity survives paraphrased news and memory pruning."""
    if isinstance(event, dict):
        known = cast.mind(npc).get("evidence", {}).get(evidence.identity(event))
        return bool(known and (not event.get("settled") or known.get("settled")))
    return event is not None and any(
        m.get("event") == event for m in evidence.held(npc) or cast.mind(npc).setdefault("memories", [])
    )


def worst_memory(npc: Npc) -> dict | None:
    """The most serious memory still standing; of equals, the newest (the bowl just taken, not the cup last week).
    Settled matters (made right, forgiven, paid for with an arrest) no longer count (D-46)."""
    memories = [
        m
        for m in evidence.held(npc) or cast.mind(npc).setdefault("memories", [])
        if not m.get("settled") and m.get("actor_id", "player") == "player"
    ]
    return max(enumerate(memories), key=lambda pair: (pair[1]["severity"], pair[0]))[1] if memories else None


def unresolved_crime(npc: Npc, kinds: tuple = ("violence", "theft", "breach")) -> dict | None:
    """The worst crime by the stranger this person knows of, believes, and that hasn't been put right."""
    crimes = [
        m
        for m in evidence.held(npc) or cast.mind(npc).setdefault("memories", [])
        if m.get("actor_id", "player") == "player"
        and m["kind"] in kinds
        and not m.get("doubted")
        and not m.get("settled")
        and m.get("severity", 0) >= 2
    ]
    return max(crimes, key=lambda m: m["severity"], default=None)


def knows_a_crime(npc: Npc) -> bool:
    """Known unresolved violence or breach, available to this person's judgment."""
    return unresolved_crime(npc, ("violence", "breach")) is not None


STANDING_WORDS = {
    "unknown": "Doesn't know you",
    "hostile": "Hostile",
    "wary": "Wary",
    "neutral": "Neutral",
    "friendly": "Friendly",
    "would_speak": "Would speak for you",
}


def standing(npc: Npc) -> str:
    """How this person stands toward the stranger, in one word for the player (D-55; never numbers): from their
    regard, their anger, and any crime they hold against them. The same rule everywhere (journal, toasts, device)."""
    my_mind = npc.get("mind") or {}
    view = my_mind.get("regard") or {}
    anger = (my_mind.get("feelings") or {}).get("anger", 0.0)
    if unresolved_crime(npc) is not None or anger >= 0.67:
        return "hostile"
    if not my_mind.get("met") and not my_mind.get("memories") and not view:
        return "unknown"
    view = regard(npc)
    family = {npc["id"], *cast.card(npc).get("family", [])}
    helped = any(
        m["kind"] in ("help", "gift") and m.get("victim") in family and m.get("clarity") != "vague"
        for m in my_mind.get("memories", [])
    )
    if view["suspicion"] >= 0.6 or my_mind.get("feelings", {}).get("fear", 0) >= 0.5:
        return "wary"
    if view["trust"] >= 0.6 or (helped and view["trust"] >= 0.3):
        return "would_speak"
    if view["trust"] >= 0.45:
        return "friendly"
    return "neutral"


def update_standing(npc: Npc) -> bool:
    """Keep mind.standing current; returns whether it changed (the client shows a toast when it does)."""
    if not npc.get("alive", True):
        return False
    now = standing(npc)
    if (npc.get("mind") or {}).get("standing") == now:
        return False
    cast.mind(npc)["standing"] = now
    return True


def settle(
    state: State,
    why: str,
    item: str | None = None,
    kinds: tuple = ("theft",),
    npc_ids: set | None = None,
    object_id: str | None = None,
) -> list[str]:
    """Mark the matching incident settled for the people who know about its resolution."""
    touched = []
    for npc in state["npcs"]:
        if npc_ids is not None and npc["id"] not in npc_ids:
            continue
        for memory in [*(npc.get("mind") or {}).get("memories", []), *evidence.held(npc)]:
            if (
                memory["kind"] in kinds
                and not memory.get("settled")
                and (object_id is None or memory.get("object_id") == object_id)
                and (item is None or memory.get("item") == item)
            ):
                memory["settled"] = why
                touched.append(npc["id"])
        update_standing(npc)
    return sorted(set(touched))


def after_deed(state: State, entry: dict) -> None:
    """What a committed deed puts right: giving someone back their own things settles that theft."""
    give = entry.get("give") if entry.get("category") in ("success", "partial_success") else None
    if not isinstance(give, dict):
        return
    for item_id in give.get("item_ids", []):
        thing = state["objects"].get(item_id)
        if thing and thing.get("owner_id") == give["recipient_id"]:
            incidents = [
                i
                for i in state.get("incidents", {}).values()
                if i.get("object_id") == item_id
                and i.get("victim") == give["recipient_id"]
                and i.get("status") == "open"
            ]
            for incident in incidents:
                incident.update(status="settled", settlement_event=entry.get("event_id"))
                # Only recipients and actual witnesses learn of restitution now.
                witnesses = {give["recipient_id"]} | {
                    n["id"]
                    for n in state["npcs"]
                    if any(
                        m.get("event") == entry.get("event_id") and m.get("kind") == "gift" for m in evidence.held(n)
                    )
                }
                settle(state, "given back", object_id=item_id, npc_ids=witnesses)


def regard(npc: Npc) -> dict:
    """How this person sees the stranger (GDD 7.2): starts from their card, changes only through events."""
    start = cast.card(npc).get("regard", {"trust": 0.2, "suspicion": 0.5})
    view = cast.mind(npc).setdefault(
        "regard", {"trust": start["trust"], "suspicion": start["suspicion"], "goodwill_used": 0.0}
    )
    view.setdefault("respect", start.get("respect", 0.0))  # Competence seen working (D-43).
    view.setdefault("awe", start.get("awe", 0.0))  # Wonder at the uncanny: double-edged (D-43).
    return view


def is_evidence(memory: Memory) -> bool:
    """Seen clearly (or told by someone), and it worked: something real in the stranger's favour."""
    return (
        memory.get("actor_id", "player") == "player"
        and memory["kind"] in EVIDENCE_KINDS
        and memory.get("clarity") != "vague"
        and memory.get("works", True)
    )


def regard_cue(npc: Npc, before: dict, after: dict) -> None:
    """A small sign the player can read when someone's view of them crosses a band. Never numbers."""

    def band(value: float, bands: tuple) -> int:
        return sum(value >= b for b in bands)

    trust = band(after["trust"], tuning.TRUST_BANDS) - band(before["trust"], tuning.TRUST_BANDS)
    suspicion = band(after["suspicion"], tuning.SUSPICION_BANDS) - band(before["suspicion"], tuning.SUSPICION_BANDS)
    if trust > 0:
        kind = "trusting" if after["trust"] >= tuning.TRUST_BANDS[-1] else "warmer"
    elif trust < 0:
        kind = "cooler"
    elif suspicion > 0:
        kind = "wary"
    elif suspicion < 0:
        kind = "easier"
    else:
        return
    count = cast.mind(npc).get("cue_count", 0) + 1
    pool = CUES[kind]
    cast.mind(npc).update(
        cue_count=count,
        cue={
            "kind": kind,
            "key": f"{npc['id']}:cue:{count}",
            "text": pool[(count + len(npc["id"])) % len(pool)].format(name=npc["name"]),
        },
    )


def _shift_regard(npc: Npc, memory: Memory) -> None:
    """Observation is evidence for a personal decision, never an automatic opinion."""
    evidence.remember(npc, memory)


FIRSTHAND = ("witnessed", "shown", "victim", "received")


def remember(npc: Npc, memory: Memory) -> None:
    """Keep durable evidence and a short episodic memory; new facts queue personal reconsideration."""
    if not evidence.remember(npc, memory):
        return
    if memory.get("severity", 0) >= 1:
        cast.mind(npc)["fresh"] = memory.get("short") or memory.get("summary", "")[:80]
    memories = cast.mind(npc).setdefault("memories", [])
    memories.append(memory)
    while len(memories) > tuning.MEMORY_LIMIT:
        memories.remove(min(memories[:-1], key=lambda m: m.get("severity", 0)))


def willing(state: State, npc: Npc) -> bool:
    """Would do the stranger a good turn now (D-59): alive and on their feet, not fighting them, not hostile to them
    (a wrong of theirs unsettled, or angry) and not afraid of them. Whatever a story asks of a person (to say their
    piece, lend, give, tell, speak for the stranger, teach) waits on this: scald Ulf and he asks for no tea."""
    if not npc.get("alive", True) or npc.get("down"):
        return False
    return npc["id"] not in ((state.get("fight") or {}).get("attackers") or [])


def will_help(state: State, npc: Npc, at: tuple[int, int] | None = None) -> bool:
    """Would lend a hand with something heavy right now (D-59): on their feet, close by (to the stranger, or to the
    thing being moved, at), not against the stranger, and either talking with them (asked) or well disposed."""
    near = min(cast.distance(npc, state["player"]), cast.distance(npc, at) if at else float("inf"))
    if not npc.get("alive", True) or npc.get("down") or near > tuning.HELP_CELLS:
        return False
    if npc["id"] in ((state.get("fight") or {}).get("attackers") or []):
        return False
    commitments = (npc.get("mind") or {}).get("commitments", [])
    return any(
        c.get("kind") == "help"
        and c.get("status") == "accepted"
        and c.get("until", state.get("sim_time_ms", 0) + 1) > state.get("sim_time_ms", 0)
        for c in commitments
    )


def hearsay(memory: Memory) -> bool:
    """Told or overheard, not their own contact with the stranger: Hessa speaking for the stranger to the captain
    doesn't mean the guards have dealt with them (D-55)."""
    source = str(memory.get("source", ""))
    return source.startswith(("told_by", "heard")) or source == "overheard"


def in_words(value: float, levels: list[str]) -> str:
    return levels[min(len(levels) - 1, int(value * len(levels)))]
