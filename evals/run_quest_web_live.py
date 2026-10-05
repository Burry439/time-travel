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


CASES = {"greetings": greetings, "inn": inn, "debts": debts}


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
