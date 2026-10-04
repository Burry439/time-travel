"""Live play-through of the village's nine storylines (D-61, D-63) with the real judge, voices and decider.

    backend/.venv/Scripts/python.exe evals/run_quests_live.py [hessa] [smithy] [compass] [beam]

Four journeys, each played the way a player might, on a temporary database without paintings (the harness of
run_routes_live.py):
- hessa: the trough water, the lodging money and Oren's debt (Darin goes and tells Oren);
- smithy: Mara's iron, Jory's tongs and Kade's knees;
- compass: lost in the fog, and something nobody knows (Jory amazed);
- beam: the gate beam.
For each story it reports the stages and outcomes reached, and for each outcome whether the people it concerns have
learned it yet (their reaction waits until they do). People decide for themselves, so a story not finished in a
journey is a finding, not necessarily a failure: read the transcript. A few tens of cents. Writes
evals/results/quests_*.txt.
"""

from __future__ import annotations

import sys
import time

import run_routes_live as routes
from run_routes_live import ROOT, Route, act, note

import reputation  # noqa: E402
import stories  # noqa: E402

TRACKED = ("trust", "suspicion", "respect", "awe")


def standing(route: Route) -> dict:
    return {n["id"]: {k: reputation.regard(n).get(k, 0.0) for k in TRACKED} for n in route.state["npcs"]}


def report(route: Route, story_ids: list[str], before: dict) -> dict:
    """What each story reached, and whom its outcomes have reached so far."""
    book = route.state.get("stories") or {}
    out = {}
    for story_id in story_ids:
        stages = (book.get("stages") or {}).get(story_id, [])
        milestones = (book.get("milestones") or {}).get(story_id, [])
        waiting = [w["npc"][4:] for w in book.get("waiting", []) if w["story"] == story_id]
        note(f"  [{story_id}] stages {stages or '-'}; outcomes {milestones or '-'}"
             + (f"; still to learn of it: {waiting}" if waiting else ""))
        for person in sorted(stories._concerned(stories.STORIES[story_id], {"effects": []}) | {
            e["npc"] for o in stories.STORIES[story_id]["outcomes"] if o["id"] in milestones for e in o.get("effects", [])
        }):
            now = standing(route).get(person, {})
            moved = {k: round(now[k] - before.get(person, {}).get(k, 0.0), 2) for k in TRACKED if person in before}
            moved = {k: v for k, v in moved.items() if v}
            if moved:
                note(f"      {person[4:]}: {moved}")
        out[story_id] = {"stages": stages, "outcomes": milestones, "waiting": waiting}
    return out


def wait(route: Route, until, seconds: int) -> bool:
    """Let the clock run (and people think) until the condition holds. Unlike run_routes_live's settle, it walks
    away from a conversation still open (the clock doesn't run during one) and reports what the clock refused."""
    for _ in range(seconds):
        if until():
            return True
        if route.state.get("encounter"):
            act(route, "leave")
            if route.state.get("encounter"):
                note("  (the conversation wouldn't close)")
                return until()
        path = "think" if route.state.get("pending_minds") else "explore"
        body = {"expected_version": route.state["event_seq"], "request_id": f"q{time.time_ns()}"}
        if path == "explore":
            body["elapsed_ms"] = 1000
        reply = routes.http.post(f"/runs/{route.run}/{path}", json=body)
        if reply.status_code == 200:
            route.state = reply.json()["state"]
        else:
            note(f"  (clock: {path} refused, {reply.status_code} {str(reply.json().get('detail'))[:120]})")
            route.state = routes.http.get(f"/runs/{route.run}").json()
    return until()


def learned(route: Route, key: str) -> bool:
    kind, _, value = key.partition(":")
    return any(e.get(kind) == value for e in route.state.get("learned", []))


def moved(route: Route, move_id: str) -> bool:
    return move_id in ((route.state.get("stories") or {}).get("moves") or [])


def hessa() -> dict:
    route = Route("Hessa and Darin: the trough water, the lodging money, Oren's debt")
    before = standing(route)
    h, d, b, o = "npc_hessa_marr", "npc_darin_ko", "npc_bren_marr", "npc_oren_dast"
    route.ask_until(h, ["Good day! Your guests look poorly. Is something going around?",
                        "Have your guests been ill? I might be able to help.",
                        "What do the sick ones have in common, do you think?"],
                    lambda: learned(route, "fact:sick_guests"))
    route.walk(75, 59)
    route.attempt("pick up the iron cooking pot")
    route.near(h)
    route.say(h, "May I use your cooking fire for a moment? I want to show you something about your water.")
    route.walk(36, 53)
    route.attempt("fill the iron pot with water from the trough and set it on the cooking fire until it boils hard")
    route.near(h)
    route.attempt("show Hessa the boiled water: boiling kills the tiny things in trough water that make people sick; "
                  "let it cool and it's safe to drink")
    route.ask_until(h, ["Boil the trough water before your guests drink it, like I showed you. Will you do that?",
                        "It costs only a little firewood, and your guests will stay well. Will you try it?"],
                    lambda: moved(route, "trust_clean_water"))
    route.ask_until(h, ["You've been good to me. Is everyone here paying their way? You look like you carry a lot.",
                        "Is any of your lodgers behind with what they owe you?",
                        "You can tell me. I won't spread it around."],
                    lambda: learned(route, "secret:hessa_darin_lodging"))
    route.ask_until(b, ["Good day. Oren seems jumpy lately. Is he in some kind of trouble?",
                        "Does Oren owe somebody money?"],
                    lambda: learned(route, "fact:oren_debt") or learned(route, "secret:bren_covers_oren"))
    route.walk(53, 67)
    route.attempt("pick up the hollow reeds and the flint shard")
    route.attempt("cut a short length of reed with the flint and carve a notch to make a whistle")
    route.near(d)
    route.attempt("give the reed whistle to Darin as a gift: something he can copy and sell")
    route.ask_until(d, ["That whistle's yours. In return, would you let Oren's debt go? He'll never pay it, and a "
                        "guard who owes you a kindness is worth more to a merchant than eleven silver.",
                        "Call it square: the whistle for Oren's debt. Will you let it go?"],
                    lambda: moved(route, "forgive_oren_debt"))
    if learned(route, "secret:hessa_darin_lodging"):
        route.ask_until(d, ["One more thing, Darin. Hessa's carried your lodging for three weeks without a word. "
                            "Pay her what you owe; her goodwill is worth more to you than the rent.",
                            "You'll want a good name in town before you trade inside the walls. Settle with Hessa?"],
                        lambda: moved(route, "settle_lodging"))
    wait(route, lambda: not any(w["npc"] in (o, h) for w in (route.state.get("stories") or {}).get("waiting", [])), 150)
    return report(route, ["trough_water", "lodging", "oren_debt"], before)


def smithy() -> dict:
    route = Route("The smithy and the patrol: Mara's iron, Jory's tongs, Kade's knees")
    before = standing(route)
    m, j, k = "npc_mara_venn", "npc_jory_venn", "npc_kade_east"
    route.ask_until(m, ["Good day. That's a big order for the guards. Have you enough good iron for it?",
                        "Where do you get your iron from, out here?"],
                    lambda: learned(route, "secret:mara_horseshoes"))
    route.walk(75, 53)
    route.attempt("pick up the iron bar")
    route.near(m)
    route.attempt("give the iron bar to Mara for the guards' order")
    route.ask_until(j, ["Hello, Jory. You look worried. Is something wrong at the forge?",
                        "You can tell me, I won't make trouble for you. Did something break?",
                        "Is it something Mara doesn't know about yet?"],
                    lambda: learned(route, "secret:jory_tongs"))
    if learned(route, "secret:jory_tongs"):
        route.near(m)
        route.say(m, "Mara, I should tell you: Jory broke your second-best tongs and hid them under the scrap.")
    route.walk(75, 59)
    route.attempt("pick up the iron cooking pot")
    route.walk(50, 17)
    route.attempt("fill the iron pot with water from the gate trough")
    route.walk(46, 64)
    route.attempt("pick up the plantain leaves")
    route.walk(50, 62)
    route.attempt("pick up the yarrow")
    route.attempt("crush the plantain leaves and yarrow together with a splash of water from the pot into a soft "
                  "poultice")
    route.near(k)
    route.say(k, "Your knees are troubling you, aren't they? I've made a poultice that eases aching joints. May I?")
    route.attempt("press the poultice gently onto Kade's aching knees")
    wait(route, lambda: False, 20)
    return report(route, ["forge_iron", "jory_tongs", "kade_knees"], before)


def compass() -> dict:
    route = Route("The compass: lost in the fog, and Jory amazed")
    before = standing(route)
    d, j, r, e = "npc_darin_ko", "npc_jory_venn", "npc_roderic_vale", "npc_elin_west"
    route.ask_until(e, ["Good day. What's the hardest part of the night watch out here?",
                        "Does the fog ever give the patrols trouble?"],
                    lambda: learned(route, "fact:fog") or learned(route, "fact:fog_patrols"))
    route.ask_until(d, ["Good day. I'm Ash. Is that a lodestone? Lend it to me for an hour and I'll show you how to "
                        "turn it into a direction-finder you could sell.",
                        "A needle stroked on your stone and floated on water points the same way every time. "
                        "You keep the stone and the idea."],
                    lambda: route.state["objects"]["lodestone_darin"].get("lent_to") == "player")
    if route.state["objects"]["lodestone_darin"].get("lent_to") != "player":
        note("  ✗ Darin would not lend the lodestone.")
        return report(route, ["fog", "jory_wonder"], before)
    route.attempt("pick up the lodestone")
    route.walk(27, 28)
    route.attempt("pick up the bent iron nail")
    route.attempt("stroke the bent iron nail many times in one direction with the lodestone to magnetise it")
    route.near(d)
    route.attempt("give the lodestone back to Darin")
    route.walk(52, 64)
    route.attempt("pick up the strip of bark")
    route.walk(45, 66)
    route.attempt("pick up the flint shard")
    route.walk(45, 54)
    route.attempt("pick up the dried gourd and cut the top off it with the flint shard to make a shallow bowl")
    route.walk(50, 17)
    route.attempt("fill the gourd bowl with water from the gate trough")
    route.near(j)
    route.attempt("float the magnetised nail on the strip of bark in the gourd bowl of water and show Jory that it "
                  "swings round by itself to point north every time I turn the bowl")
    route.near(r)
    route.attempt("float the magnetised nail on the bark in the gourd bowl and show Captain Roderic and Elin that it "
                  "always swings back to point north, even when I turn the bowl")
    route.near(r)
    route.attempt("give Captain Roderic the magnetised nail and the strip of bark so his patrols can find north in fog")
    wait(route, lambda: False, 10)
    return report(route, ["fog", "jory_wonder"], before)


def beam() -> dict:
    route = Route("The gate beam")
    before = standing(route)
    tomas, bren = "npc_tomas_reed", "npc_bren_marr"
    route.ask_until(tomas, ["Good day, I'm Ash. That gate beam looks like trouble. I know how to raise heavy things "
                            "safely with a rope and a ladder.",
                            "I could get it up into the brackets for you, if you'll let me."],
                    lambda: route.deal(tomas, "proposed") or route.deal(tomas, "accepted"))
    route.ask_until(tomas, ["Agreed, I'll get it up for you.", "Yes, it's a deal."],
                    lambda: route.deal(tomas, "accepted"))
    route.ask_until(tomas, ["May I borrow your rope and your ladder for it? Rope over the bracket, ladder to guide it.",
                            "Just the rope and the ladder, and they come straight back."],
                    lambda: all(route.state["objects"][i].get("lent_to") == "player" for i in ("rope_tomas", "ladder_tomas")))
    route.attempt("pick up the coil of rope and the wooden ladder")
    route.walk(54, 14)
    wait(route, lambda: bool(route.state.get("encounter")), 4)
    if route.state.get("encounter"):
        act(route, "say", "I'm working for Tomas the carpenter: I'm here to raise the new gate beam.")
        act(route, "leave")
    route.attempt("set the ladder against the gate, climb it, lift one end of the cracked gate bar out of its bracket "
                  "and lower it down on the rope, then the other end, and lay the old bar on the ground")
    method = ("set the ladder against the gate beside the brackets, loop the rope over the iron brackets and tie it to "
              "one end of the beam, haul that end up from the ground while resting it on the ladder rungs between "
              "pulls, guide it into its bracket from the ladder, then do the same with the other end")
    entry = route.attempt(method)
    if entry.get("category") != "success" and "help" in entry.get("reason", "").lower():
        route.ask_until(bren, ["Bren, would you lend me a hand raising the new beam for Tomas? Just hold the ladder "
                               "and steady the far end.", "It'll take a moment, and the gate's safer for it."],
                        lambda: any(c.get("status") == "accepted"
                                    for c in (route.person(bren).get("mind") or {}).get("commitments", [])))
        route.walk(54, 14)
        route.attempt(method + ", with Bren holding the ladder and steadying the far end")
    note("  (the beam is up in its brackets)" if route.state["objects"]["gate_beam"].get("installed_in")
         else "  ✗ The beam didn't go up.")
    route.ask_until(tomas, ["That old bar cracked badly. How did it happen?",
                            "Between us: did something go wrong with the first beam?",
                            "You can tell me. It stays between us."],
                    lambda: learned(route, "secret:tomas_cracked"))
    wait(route, lambda: False, 10)
    return report(route, ["gate_beam"], before)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    wanted = sys.argv[1:] or ["hessa", "smithy", "compass", "beam"]
    started = time.perf_counter()
    results = {name: globals()[name]() for name in wanted}
    note(f"\nRESULTS in {time.perf_counter() - started:.0f} s")
    for name, found in results.items():
        for story_id, got in found.items():
            note(f"  {story_id:13} outcomes {got['outcomes'] or '-'}  stages {got['stages'] or '-'}"
                 + (f"  waiting {got['waiting']}" if got["waiting"] else ""))
    out = ROOT / "evals" / "results" / f"quests_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    out.write_text("\n".join(routes.log), encoding="utf-8")
    print(f"Transcript: {out.relative_to(ROOT)}")
