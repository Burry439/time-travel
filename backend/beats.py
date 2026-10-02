"""Story beats (D-59): what a level's story has someone get across is said in their own words, in the reply that
brings the moment about, not as an authored line after it.

A step's authored lines (npc_says) are what its people get across when it completes, with the next step's opening
lines, which follow at once; a trigger's, when it fires. (A lead or an offer that quotes someone always comes with
their line, so what the journal quotes is what they said.) When a round is about to bring one of those moments about
(the stranger's words or deed make the check hold) and someone it gives words to may speak in that round, the voice
gets their substance to weave into the reply: Wenna, asked how she is, says she's parched and asks for water,
instead of "fine" followed by a scripted request. A moment the reply itself decides (a deal judged done, being let
across) comes with only_if: they bring it up only if they decide it.

What they said in the round that brought the moment about is their answer to it. Their authored line is then said
only for what that answer left out, sentence by sentence (code compares the words): nothing if they said it all,
"Tell her Wenna sent you." if that was all they missed, the whole line if they spoke of something else or didn't
speak at all. A lead quotes their own words only if those carry it. The voice's own flag (brought_up_story_beat)
is kept for telemetry: a model can say it told what it left out.

Code decides when a beat is due, whether its moment came and what is still to say; the voice only words it
(GDD 1)."""

from __future__ import annotations

import re

import cast
import content
import conversation
import rules
from shapes import Npc, State

COVERED = 0.5  # A sentence is said if more than this share of its key words are in what they said.
SMALL_WORDS = frozenset(
    re.findall(
        r"\w+",
        """a an the and or but if so then than to of in on at by up for from into out off over with about as is it its be
    am are was were been do does did have has had i me my mine you your yours we us our he him his she her hers they
    them their this that these those there here what who whom which when where why how all any not no yes just now too
    very can will would could should shall may might must get got one ll re ve oh ah ahh hm hmm listen""",
    )
)

# Conditions a reply itself can make hold: the decision that does it, and the move it takes (None: a reading).
DECIDED = {
    "admitted": ("you let the stranger through (admit)", "admit"),
    "inside": ("you let the stranger in (admit)", "admit"),
    "knows": ("you tell the stranger what you've kept to yourself (share)", "share"),
    "standing": ("you now think well of the stranger", None),
    "lent": ("you lend it to the stranger (lend)", "lend"),
    "vouched": ("you go and speak for the stranger (vouch)", "vouch"),
}
DEAL_DECIDED = {
    "proposed": ("you offer the stranger the deal (offer)", "offer"),
    "accepted": ("the stranger has agreed to your deal (agreed_to_the_deal)", None),
    "fulfilled": ("you judge the job you asked for done (did_what_was_asked)", None),
}


def _decided(spec: dict) -> tuple[str, str | None] | None:
    """The decision in a reply that makes this one condition hold, and its move, if a reply can make it hold."""
    if spec["kind"] == "deal":
        return DEAL_DECIDED.get(spec["status"])
    if spec["kind"] == "remembers" and spec.get("settled"):
        return ("you let what they did go (forgive)", "forgive")
    return DECIDED.get(spec["kind"])


def _decision(spec: dict) -> tuple[str, str | None] | None:
    """The first decision a reply could make within a condition (all / any look inside; not never does)."""
    if spec["kind"] in ("all", "any"):
        return next((found for part in spec["of"] if (found := _decision(part))), None)
    return None if spec["kind"] == "not" else _decided(spec)


def _open_to(state: State, npc: Npc, move: str | None) -> bool:
    """Whether this person could make that decision now: a reading always; a move only if it's one of theirs now
    (Gorm isn't offered a yes before anyone has spoken for the stranger, so his "get aboard" waits too)."""
    return move is None or any(k == move or k.startswith(f"{move}:") for k in conversation.moves(state, npc))


def answered(npc: Npc, key: str | None) -> str | None:
    """What this person said, in their own words, in the round that brought this moment about (None if nothing)."""
    return (cast.mind(npc).get("answered") or {}).get(key) if key else None


def mark_answered(npc: Npc, beat: dict, line: str) -> None:
    """What they said in the round that brought this beat's moments about: their answer to each."""
    for key in beat["keys"]:
        cast.mind(npc).setdefault("answered", {})[key] = line


def _key_words(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in SMALL_WORDS}


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _short(sentence: str) -> bool:
    """A word or two ("Help?", "Deal?", "Hm."): an interjection, never worth saying on its own afterwards."""
    return len(re.findall(r"[A-Za-z']+", sentence)) <= 2


def _covered(sentence: str, said: str) -> bool:
    """Said already: more than half its key words are in what they said ("My cup's by the well" needs the cup, not
    only the well)."""
    keys = _key_words(sentence)
    return not keys or len(keys & _key_words(said)) > COVERED * len(keys)


def left_to_say(text: str, said: str | None) -> str:
    """What of an authored line is still to say after what they said themselves: the part their words didn't reach.
    People tell a thing in order, so a sentence before one they said was said their own way (a thirsty woman's
    "I'm parched" for "Water, that's what's wrong"), and only what comes after the last one they said is left,
    without any interjection they already used. Nothing left but an interjection is nothing left."""
    if said is None:
        return text
    sentences = _sentences(text)
    reached = [i for i, s in enumerate(sentences) if not _short(s) and _covered(s, said)]
    rest = sentences[reached[-1] + 1 :] if reached else sentences
    rest = [s for s in rest if not (_short(s) and _covered(s, said))]
    return "" if all(_short(s) for s in rest) else " ".join(rest)


def says_all(said: str | None, text: str) -> bool:
    """Whether what they said carries every sentence of this (what a lead quotes)."""
    return said is not None and not left_to_say(text, said)


def words(state: State, effects: list[dict], ctx: dict) -> dict[str, str]:
    """What each person says in these effects, their authored lines joined: {npc_id: words}."""
    said: dict[str, list[str]] = {}
    for spec in effects:
        if spec["kind"] == "npc_says" and spec["npc"] != "player" and rules.holds(state, spec.get("when"), ctx):
            said.setdefault(spec["npc"], []).append(spec["text"])
    return {npc_id: " ".join(lines) for npc_id, lines in said.items()}


Moment = tuple[dict, list[tuple[str, list[dict]]]]  # A condition, and the effects it sets off, each with its key.


def moments(state: State) -> list[Moment]:
    """The story moments that could come next: each of the running step's triggers not yet fired (key step:trigger);
    its completion: its on_done (key step) and the next step's on_start (key next:start), which follows at once;
    and the next step's completion as well, since one round can bring both about (the trough filled in front of
    Ada, and her judging the job done), once both hold. None while the step's cards are still being read (its
    check doesn't count yet)."""
    current = rules.scene_step(state)
    progress = state.get("tutorial") or {}
    if current is None or progress.get("read", progress.get("step", 0)) < progress.get("step", 0):
        return []
    found: list[Moment] = [
        (t["when"], [(f"{current['id']}:{t['id']}", t["do"])])
        for t in current.get("triggers", [])
        if f"{current['id']}:{t['id']}" not in progress.get("fired", [])
    ]
    steps = content.level(state)["steps"]
    following = steps[progress["step"] + 1 : progress["step"] + 3]
    found.append((current["check"], _completion(current, following[:1])))
    if following:
        both = {"kind": "all", "of": [current["check"], following[0]["check"]]}
        found.append((both, _completion(following[0], following[1:])))
    return found


def _completion(step: dict, following: list[dict]) -> list[tuple[str, list[dict]]]:
    """What a step's completion sets off: its on_done, then the next step's on_start."""
    parts = [(step["id"], step.get("on_done", []))]
    return parts + [(f"{after['id']}:start", after.get("on_start", [])) for after in following]


def came(state: State, beat: dict) -> bool:
    """Whether this beat's moment holds now: the reply that told it really brought it about (code may still have
    refused what the voice proposed, like a ferryman's yes with nothing to go on)."""
    ctx = {"now": state.get("sim_time_ms", 0), "progress": state.get("tutorial") or {}}
    return any(
        beat["keys"][0] in (key for key, _ in parts) and rules.holds(state, when, ctx) for when, parts in moments(state)
    )


def due(draft: State, addressed_id: str, text: str, happened: str | None, now: int) -> dict[str, dict]:
    """The beats due in this round's replies, by person: {npc_id: {keys, get_across, only_if?}}. A moment is due
    when it will hold once the stranger's words are heard (the deed is already on the draft), or could hold by a
    decision the reply makes (only_if). One beat per person: the first moment that gives them words."""
    found: dict[str, dict] = {}
    upcoming = moments(draft)
    if not upcoming:
        return found
    heard = _heard(draft, addressed_id, conversation.said_or_did(text, happened), now)
    ctx = {"now": now, "progress": draft.get("tutorial") or {}}
    for when, parts in upcoming:
        decision = None
        if not rules.holds(heard, when, ctx):
            decision = _decision(when)
            if decision is None or not rules.holds(heard, when, ctx | {"assume": _decided}):
                continue
        here: dict[str, dict] = {}
        for key, effects in parts:
            for npc_id, gist in words(heard, effects, ctx).items():
                npc = cast.find(draft["npcs"], npc_id)
                if npc_id in found or npc is None or answered(npc, key) is not None:
                    continue
                if decision and not _open_to(draft, npc, decision[1]):
                    continue  # Theirs to decide, but not open to them yet: the beat waits.
                beat = here.setdefault(npc_id, {"keys": [], "get_across": []})
                beat["keys"].append(key)
                beat["get_across"].append(gist)
        for npc_id, beat in here.items():
            found[npc_id] = {"keys": beat["keys"], "get_across": " ".join(beat["get_across"])}
            found[npc_id] |= {"only_if": decision[0]} if decision else {}
    return found


def _heard(draft: State, addressed_id: str, said: str, now: int) -> State:
    """The draft as it will be once the addressed person has heard the stranger (their words or deed): a view for
    checking conditions, not a change. Only the addressed person is copied."""
    turn = {"who": "stranger", "text": said, "at": now}
    heard = dict(draft)
    heard["npcs"] = [
        n | {"mind": cast.mind(n) | {"talk": [*cast.mind(n).get("talk", []), turn]}} if n["id"] == addressed_id else n
        for n in draft["npcs"]
    ]
    return heard
