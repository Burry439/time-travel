"""What each person remembers of the stranger, and what follows from it: their regard (trust, suspicion,
respect, awe), the crimes they hold against them, and the one word the player sees for where they stand
(GDD 7.2, D-46, D-55). Memories change only through events."""

from __future__ import annotations

import cast
import content
import tuning
from shapes import Memory, Npc, State

CUES: dict[str, list[str]] = content.LINES["cues"]


FEAR_LEVELS = ["Not afraid", "Uneasy", "Afraid", "Terrified"]


ANGER_LEVELS = ["Calm", "Annoyed", "Angry", "Furious"]


EVIDENCE_KINDS = ("demonstration", "vouch", "help", "gift")  # Good things seen or heard about the stranger.


CRIME_KINDS = ("violence", "theft", "breach")  # breach: unbarring the city gate (D-42).


def knows(npc: Npc, event) -> bool:
    """Already has a memory of this event (so news about it is not new)."""
    return event is not None and any(m.get("event") == event for m in cast.mind(npc)["memories"])


def worst_memory(npc: Npc) -> dict | None:
    """The most serious memory still standing; of equals, the newest (the bowl just taken, not the cup last week).
    Settled matters (made right, forgiven, paid for with an arrest) no longer count (D-46)."""
    memories = [m for m in cast.mind(npc)["memories"] if not m.get("settled")]
    return max(enumerate(memories), key=lambda pair: (pair[1]["severity"], pair[0]))[1] if memories else None


def unresolved_crime(npc: Npc, kinds: tuple = ("violence", "theft", "breach")) -> dict | None:
    """The worst crime by the stranger this person knows of, believes, and that hasn't been put right."""
    crimes = [
        m
        for m in cast.mind(npc)["memories"]
        if m["kind"] in kinds and not m.get("doubted") and not m.get("settled") and m.get("severity", 0) >= 2
    ]
    return max(crimes, key=lambda m: m["severity"], default=None)


def knows_a_crime(npc: Npc) -> bool:
    """A known act of real violence, or an assault on the gate: what rules out entry for good, and what makes
    someone fight to kill rather than to subdue (D-44). Theft and arrests only weigh on their judgement."""
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
    if view["suspicion"] >= 0.6:
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
    state: State, why: str, item: str | None = None, kinds: tuple = ("theft",), npc_ids: set | None = None
) -> list[str]:
    """A matter is put right (the thing given back, forgiven, paid for with an arrest): everyone who held it
    against the stranger lets it go (D-46). Regard already moved stays moved; the grudge ends."""
    touched = []
    for npc in state["npcs"]:
        if npc_ids is not None and npc["id"] not in npc_ids:
            continue
        for memory in (npc.get("mind") or {}).get("memories", []):
            if memory["kind"] in kinds and not memory.get("settled") and (item is None or memory.get("item") == item):
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
            settle(state, "given back", item=thing["name"])


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
    return memory["kind"] in EVIDENCE_KINDS and memory.get("clarity") != "vague" and memory.get("works", True)


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
    """Evidence raises trust and eases suspicion; a crime does the opposite. Once per event."""
    view = regard(npc)
    credited = view.setdefault("credited", [])
    if memory.get("event") is not None and memory.get("event") in credited:
        return
    if is_evidence(memory):
        trust, suspicion = tuning.EVIDENCE_SHIFT, -tuning.EVIDENCE_SHIFT
    elif memory["kind"] in CRIME_KINDS and memory.get("clarity") != "vague":
        trust, suspicion = -2 * tuning.EVIDENCE_SHIFT, 2 * tuning.EVIDENCE_SHIFT
    elif memory["kind"] == "arrest":
        trust, suspicion = -tuning.EVIDENCE_SHIFT, tuning.EVIDENCE_SHIFT
    else:
        return
    if memory.get("event") is not None:
        credited.append(memory["event"])
    before = dict(view)
    if is_evidence(memory) and memory["kind"] == "demonstration":
        trust, suspicion = _wonder(npc, memory, view, trust, suspicion)
    view["trust"] = round(min(1.0, max(0.0, view["trust"] + trust)), 3)
    view["suspicion"] = round(min(1.0, max(0.0, view["suspicion"] + suspicion)), 3)
    regard_cue(npc, before, view)


FIRSTHAND = ("witnessed", "shown", "victim", "received")


def _wonder(npc: Npc, memory: Memory, view: dict, trust: float, suspicion: float) -> tuple[float, float]:
    """Something that worked earns respect; something uncanny, seen with their own eyes, earns awe, and what
    awe does depends on who they are (their superstition): reverence, or fear of witchcraft. Hearsay earns
    neither awe nor fear: claims and stories never do (GDD 1)."""
    wonder = memory.get("wonder", "ordinary")
    view["respect"] = round(min(1.0, view["respect"] + tuning.RESPECT_SHIFT.get(wonder, tuning.EVIDENCE_SHIFT)), 3)
    if wonder != "uncanny" or memory.get("source") not in FIRSTHAND:
        return trust, suspicion
    view["awe"] = round(min(1.0, view["awe"] + tuning.AWE_SHIFT), 3)
    leaning = (cast.card(npc).get("superstition") or {}).get("kind", "none")
    if leaning == "reverent":
        return trust + tuning.EVIDENCE_SHIFT, suspicion - tuning.EVIDENCE_SHIFT
    if leaning == "wary":  # Witchcraft: no credit for it, and afraid of whoever did it.
        feelings = cast.mind(npc)["feelings"]
        feelings["fear"] = max(feelings.get("fear", 0.0), 0.34)
        return 0.0, 2 * tuning.EVIDENCE_SHIFT
    return trust, suspicion


def remember(npc: Npc, memory: Memory) -> None:
    """Add a memory (evidence and crimes move regard); past the limit, forget the least serious one.
    Anything of note makes them fresh: they'll reconsider their day (D-39: the decider on events, not a timer)."""
    _shift_regard(npc, memory)
    if memory.get("severity", 0) >= 1:
        cast.mind(npc)["fresh"] = memory.get("short") or memory.get("summary", "")[:80]
    memories = cast.mind(npc)["memories"]
    memories.append(memory)
    while len(memories) > tuning.MEMORY_LIMIT:
        memories.remove(min(memories[:-1], key=lambda m: m.get("severity", 0)))


def will_help(state: State, npc: Npc) -> bool:
    """Would lend a hand with something heavy right now (D-59): on their feet, close by, not against the stranger,
    and either talking with them (asked) or well disposed toward them."""
    if not npc.get("alive", True) or npc.get("down") or cast.distance(npc, state["player"]) > tuning.HELP_CELLS:
        return False
    if npc["id"] in ((state.get("fight") or {}).get("attackers") or []):
        return False
    where = standing(npc)
    talking = npc["id"] in ((state.get("encounter") or {}).get("participants") or [])
    return where not in ("hostile", "wary") and (talking or where in ("friendly", "would_speak"))


def hearsay(memory: Memory) -> bool:
    """Told or overheard, not their own contact with the stranger: Hessa speaking for the stranger to the captain
    doesn't mean the guards have dealt with them (D-55)."""
    source = str(memory.get("source", ""))
    return source.startswith(("told_by", "heard")) or source == "overheard"


def in_words(value: float, levels: list[str]) -> str:
    return levels[min(len(levels) - 1, int(value * len(levels)))]
