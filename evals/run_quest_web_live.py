"""Live check of the village's quests (D-67): people speak first and raise what's on their mind; a quest is played
through its steps by a player's own words and deeds; and one quest crosses into another, so the second person sees
the first quest from their side.

    backend/.venv/Scripts/python.exe evals/run_quest_web_live.py [greetings] [inn] [debts] [permit]

Plays from fresh journeys on a temporary database, through the routes the game uses, with the real judge and voices
and no paintings. A few cents a case. Writes evals/results/quest_web_*.txt.
"""

from __future__ import annotations

import sys
import time

import run_routes_live as routes
from run_routes_live import ROOT, Route, note

import cast  # noqa: E402  (run_routes_live put backend on the path)

ELIN, KADE, MARA, TOMAS = "npc_elin_west", "npc_kade_east", "npc_mara_venn", "npc_tomas_reed"
HESSA, BREN, DARIN, OREN, JORY, RODERIC = (
    "npc_hessa_marr",
    "npc_bren_marr",
    "npc_darin_ko",
    "npc_oren_dast",
    "npc_jory_venn",
    "npc_roderic_vale",
)


def greet(route: Route, npc_id: str) -> str:
    """Walk up to someone: they speak first. Their first line, as said."""
    route.near(npc_id)
    body = {"kind": "greet", "target_id": npc_id, "expected_version": route.state["event_seq"],
            "request_id": f"g{time.time_ns()}"}
    reply = routes.http.post(f"/runs/{route.run}/encounter/act", json=body)
    if reply.status_code != 200:
        note(f"  GREET {npc_id[4:]}: !! {reply.status_code} {str(reply.json().get('detail'))[:200]}")
        return ""
    data = reply.json()
    route.state = data.get("state", route.state)
    lines = [e["text"] for e in data["round"]["entries"] if e.get("who") == npc_id]
    note(f"  GREET {cast.find(route.state['npcs'], npc_id)['name']}: {' | '.join(lines)[:300]}")
    return " ".join(lines)


def leave(route: Route) -> None:
    body = {"kind": "leave", "expected_version": route.state["event_seq"], "request_id": f"l{time.time_ns()}"}
    reply = routes.http.post(f"/runs/{route.run}/encounter/act", json=body)
    if reply.status_code == 200:
        route.state = reply.json().get("state", route.state)


def deed(route: Route, text: str) -> dict:
    reply = routes.http.post(f"/runs/{route.run}/act", json={
        "text": text, "selected_ids": [], "mode": "do", "expected_version": route.state["event_seq"],
        "request_id": f"d{time.time_ns()}"})
    data = reply.json()
    route.state = data.get("state", route.state)
    entry = route.state.get("last_action") or {}
    note(f"  DO: {text}\n    [{entry.get('category')}] {str(entry.get('reason', ''))[:220]}")
    return entry


def stages(route: Route, quest: str) -> list[str]:
    return (route.state.get("stories") or {}).get("stages", {}).get(quest, [])


def endings(route: Route, quest: str) -> list[str]:
    return (route.state.get("stories") or {}).get("milestones", {}).get(quest, [])


def report(route: Route, *quests: str) -> None:
    for quest in quests:
        note(f"  {quest}: steps {stages(route, quest)} endings {endings(route, quest)}")


def sides(route: Route, npc_id: str) -> dict:
    return (cast.find(route.state["npcs"], npc_id).get("mind") or {}).get("sides", {})


# --- Cases -------------------------------------------------------------------------------------------------------


def greetings() -> bool:
    """Bren, Darin and Hessa each bring up their trouble when the stranger comes up to them, unasked."""
    hooks = {BREN: ("oren",), DARIN: ("sell", "new", "goods", "trade", "buy"), HESSA: ("sick", "trough", "guest")}
    raised = 0
    for npc_id, words in hooks.items():
        route = Route(f"greet {npc_id[4:]}")
        line = greet(route, npc_id).lower()
        hit = any(w in line for w in words)
        raised += hit
        note(f"  raises it: {hit}")
    return raised >= 2


def inn() -> bool:
    """The Wayside Inn, by talk and deed: sick guests, the cause, the trough cleaned, clean water to Hessa, and what
    else she'd tell someone who helped."""
    route = Route("the wayside inn")
    greet(route, HESSA)
    route.ask_until(HESSA, ["What happened with your guests?", "Has anything changed about the trough lately?",
                            "Anything odd about the trough itself, the boards or the spout?"],
                    lambda: "cause" in stages(route, "trough_water"))
    leave(route)
    route.walk(47, 66)
    route.attempt("pick up the fallen branch")
    route.walk(37, 53)
    deed(route, "use the branch to pry up the soft boards by the trough's spout, dig out whatever is rotting under there, and bail "
                "the foul water out so it refills clean")
    route.walk(35, 53)
    deed(route, "pick up Hessa's wooden bucket, fill it from the trough, and carry it to Hessa")
    route.near(HESSA)
    deed(route, "give Hessa the bucket of clean water")
    route.say(HESSA, "There was something dead rotting under the trough boards. I dug it out and bailed it; that "
                     "water's clean now.")
    route.ask_until(HESSA, ["Is anything else weighing on you, Hessa? I'd like to help if I can.",
                            "Anyone slow to pay at the inn?"],
                    lambda: any(e.get("secret") == "hessa_darin_lodging" for e in route.state.get("learned", [])))
    report(route, "trough_water", "oren_debt", "darin_permit")
    note(f"  Hessa's side: {sides(route, HESSA).get('trough_water', {}).get('text', '')[:200]}")
    return {"sick", "cause", "clean"} <= set(stages(route, "trough_water"))


def debts() -> bool:
    """Dice and Debts from Bren's ask to the debt answered, and the crossing: Darin's name in town comes clean."""
    route = Route("dice and debts")
    greet(route, BREN)
    route.say(BREN, "What's wrong with Oren, do you think?")
    leave(route)
    route.near(JORY)
    route.say(JORY, "Jory, have you seen anything odd with Oren the guard lately?")
    leave(route)
    route.walk(51, 65)
    route.attempt("pick up the hollow reeds and the flint shard")
    route.attempt("cut a short length of reed with the flint and carve a notch to make a whistle")
    route.near(DARIN)
    route.attempt("blow the reed whistle for Darin to show him how loud and clear it is")
    route.say(DARIN, "A whistle anyone could carry, cut from a reed in a minute. Herders and travellers would buy "
                     "them by the dozen.")
    route.ask_until(DARIN, ["I hear Oren lost to you at dice. What does he owe you?",
                            "What do you mean to do about Oren's debt?"],
                    lambda: "debt" in stages(route, "oren_debt"))
    route.ask_until(DARIN, ["You've something to sell now. What stands between you and trading inside the walls?",
                            "What do you still need before you can trade in the city?"],
                    lambda: any(e.get("fact") == "needs_seal" or e.get("secret") == "darin_permit"
                                for e in route.state.get("learned", [])))
    route.ask_until(DARIN, ["Then think on it: Roderic asks around town before he seals your permit. Squeezing a "
                            "gate guard over dice would sour him on you. Let Oren's debt go, and you've a friend at "
                            "the gate instead.",
                            "Take the whistle, and the know-how to make a hundred more, for Oren's debt. Call it "
                            "square, and you'll have a friend at the gate instead of a frightened boy.",
                            "Here: the whistle is yours. That's worth more than eleven silver to a merchant. "
                            "Will you call Oren's debt paid?"],
                    lambda: "answered" in stages(route, "oren_debt"),)
    if "answered" not in stages(route, "oren_debt"):
        deed(route, "give Darin the reed whistle as payment for Oren's debt")
        route.ask_until(DARIN, ["That whistle's yours now, for Oren's debt. Square?",
                                "Call Oren's eleven silver paid with it, would you?"],
                        lambda: "answered" in stages(route, "oren_debt"))
    report(route, "oren_debt", "darin_permit", "trough_water")
    note(f"  Darin's side of the debt: {sides(route, DARIN).get('oren_debt', {}).get('text', '')[:200]}")
    note(f"  Darin's side of the permit: {sides(route, DARIN).get('darin_permit', {}).get('text', '')[:200]}")
    return {"troubled", "debt", "answered"} <= set(stages(route, "oren_debt")) and "clean_name" in stages(
        route, "darin_permit")


def fog() -> bool:
    """Lost in the Fog: Elin's ask, a north-finder made from Darin's lodestone and a nail, proven in front of the
    watch and put in their hands; then the captain's own call on Elin."""
    route = Route("lost in the fog")
    greet(route, ELIN)
    route.say(ELIN, "How does the fog beat the patrols? What would help?")
    leave(route)
    route.ask_until(DARIN, ["Good day. Is that a lodestone? Lend it to me for an hour and I'll show you how to turn it "
                            "into a direction-finder you could sell.",
                            "A needle stroked on your stone and floated on water points the same way every time. You "
                            "keep the stone and the idea."],
                    lambda: route.state["objects"]["lodestone_darin"].get("lent_to") == "player")
    leave(route)
    route.attempt("pick up the lodestone")
    route.walk(27, 28)
    route.attempt("pick up the bent iron nail")
    route.attempt("stroke the bent iron nail many times in one direction with the lodestone to magnetise it")
    route.walk(52, 64)
    route.attempt("pick up the strip of bark")
    route.walk(45, 66)
    route.attempt("pick up the flint shard")
    route.walk(45, 54)
    route.attempt("pick up the dried gourd and cut the top off it with the flint shard to make a shallow bowl")
    route.walk(50, 17)
    route.attempt("fill the gourd bowl with water from the gate trough")
    route.near(ELIN)
    route.attempt("float the magnetised nail on the strip of bark in the gourd bowl and show Elin and the captain "
                  "that it always swings back to point north, even when I turn the bowl")
    route.attempt("give Elin the magnetised nail and the strip of bark so the patrols can find north in fog")
    route.ask_until(RODERIC, ["Captain, the watch can find north in fog now. Elin knows how it works. Will you let "
                              "her lead the next fog patrol?",
                              "Elin's the one to lead with it. Will you have her at your side?"],
                    lambda: "elin_trusted" in endings(route, "fog"))
    report(route, "fog", "kade_knees")
    note(f"  Elin's side: {sides(route, ELIN).get('fog', {}).get('text', '')[:200]}")
    return {"problem", "heading", "proven"} <= set(stages(route, "fog"))


def knees() -> bool:
    """The Old Soldier, and its crossing: Kade's knees eased with a warm compress, his truth about Aldo, carried to
    Hessa, whose side of him changes."""
    route = Route("the old soldier")
    greet(route, ELIN)
    route.say(ELIN, "What's wrong with Kade? He's limping.")
    leave(route)
    route.walk(51, 66)
    route.attempt("pick up the flat stone")
    route.walk(60, 59)
    route.attempt("pick up the tuft of sheep's wool")
    route.walk(37, 53)
    route.attempt("set the flat stone in the edge of Hessa's cooking fire until it's hot, then wrap it in the wool")
    route.near(KADE)
    route.attempt("hold the wool-wrapped warm stone to Kade's aching knee to ease it")
    route.ask_until(KADE, ["Better? Warmth helps a joint that's worn. How did your knees go, Kade?",
                           "There's a story in those knees. You can tell me, if you want."],
                    lambda: "why" in stages(route, "kade_knees"))
    leave(route)
    route.near(HESSA)
    route.say(HESSA, "Hessa, there's something you should know about Kade. The night Aldo was lost, Kade went back "
                     "into the fog for him, twice, and broke his knees on the rocks looking. He's carried Aldo's horn "
                     "ever since.")
    report(route, "kade_knees", "trough_water", "fog")
    note(f"  Hessa's side of the inn: {sides(route, HESSA).get('trough_water', {}).get('text', '')[:220]}")
    note(f"  Kade's side: {sides(route, KADE).get('kade_knees', {}).get('text', '')[:200]}")
    return {"limp", "why", "hessa_hears"} <= set(stages(route, "kade_knees")) and "old_grief" in stages(
        route, "trough_water")


def forge() -> bool:
    """The Guards' Order: Mara's ask, fuel from the ash heap, iron from the wainwright's yard, and the crossing: Mara
    sends Tomas his nails, a step of the gate beam."""
    route = Route("the guards' order")
    greet(route, MARA)
    route.say(MARA, "What's the trouble with the guards' order?")
    leave(route)
    route.walk(12, 27)
    route.attempt("pick up the lump of charcoal")
    route.near(MARA)
    deed(route, "give Mara the lump of charcoal for her forge")
    route.walk(76, 52)
    route.attempt("pick up the iron bar")
    route.near(MARA)
    deed(route, "give Mara the iron bar for the guards' order")
    route.ask_until(MARA, ["Tomas needs nails and iron straps for the gate brackets. Could you spare him some now "
                           "you've iron again?",
                           "Would you send Tomas the nails for his brackets? He can't raise the beam without them."],
                    lambda: "nails" in stages(route, "gate_beam"))
    report(route, "forge_iron", "gate_beam", "jory")
    note(f"  Tomas's side of the beam: {sides(route, TOMAS).get('gate_beam', {}).get('text', '')[:200]}")
    return {"order", "fuel", "good_iron"} <= set(stages(route, "forge_iron"))


def apprentice() -> bool:
    """The Apprentice: a wonder for Jory, the tongs he broke, dug out from under the scrap, and owning up to Mara."""
    route = Route("the apprentice")
    route.walk(51, 65)
    route.attempt("pick up the hollow reeds and the flint shard")
    route.attempt("cut a short length of reed with the flint and carve a notch to make a whistle")
    greet(route, JORY)
    route.attempt("blow the reed whistle for Jory and show him how the notch makes the note")
    route.ask_until(JORY, ["You look like something's weighing on you, Jory. What's wrong?",
                           "Whatever it is, I won't run to your aunt. What happened?"],
                    lambda: "broken" in stages(route, "jory"))
    route.ask_until(JORY, ["Dig the tongs out from under the scrap and let's see how bad it is. Maybe we can mend them.",
                           "Show me where you hid them. Broken iron can be mended."],
                    lambda: "found" in stages(route, "jory"))
    route.ask_until(JORY, ["Your aunt will think more of you if you tell her yourself than if she finds out. Go on, "
                           "I'll stand with you.",
                           "Owning up beats being found out, Jory. Tell her."],
                    lambda: "mara_knows" in stages(route, "jory"))
    report(route, "jory", "forge_iron")
    note(f"  Mara's side of Jory: {sides(route, MARA).get('jory', {}).get('text', '')[:200]}")
    return {"broken", "found"} <= set(stages(route, "jory"))


CASES = {"greetings": greetings, "inn": inn, "debts": debts, "fog": fog, "knees": knees, "forge": forge, "apprentice": apprentice}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    wanted = sys.argv[1:] or list(CASES)
    results = {}
    for name in wanted:
        try:
            results[name] = CASES[name]()
        except Exception as error:  # A broken case is a finding, not the end of the run.
            note(f"  !! {type(error).__name__}: {error}")
            results[name] = False
        note(f"  => {'PASS' if results[name] else 'FAIL'}")
    note(f"\nRESULTS: {sum(results.values())}/{len(results)}  " + ", ".join(
        f"{k} {'ok' if v else 'FAIL'}" for k, v in results.items()))
    out = ROOT / "evals" / "results" / f"quest_web_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    out.write_text("\n".join(routes.log), encoding="utf-8")
    print(f"Transcript: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
