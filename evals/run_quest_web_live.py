"""Live check of the village's quests (D-69): people speak first and raise what's on their mind; a quest is played
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
    """The Wayside Inn, by talk and deed: sick guests, the cause, clean water, the lodging, Bren's secret."""
    route = Route("the wayside inn")
    greet(route, HESSA)
    route.say(HESSA, "Sick guests? What do you think is wrong with the trough water?")
    route.say(HESSA, "Has anything changed about the trough lately?")
    leave(route)
    route.walk(37, 53)
    deed(route, "pry up the soft boards by the trough's spout, dig out whatever is rotting under there, and bail "
                "the foul water out so it refills clean")
    route.near(HESSA)
    route.say(HESSA, "I cleaned out the trough: there was something dead under the boards. The water should be "
                     "sweet now.")
    route.ask_until(HESSA, ["Is anything else weighing on you, Hessa? I'd like to help if I can.",
                            "Anyone giving you trouble at the inn?"],
                    lambda: "lodging" in stages(route, "trough_water") or any(
                        e.get("secret") == "hessa_darin_lodging" for e in route.state.get("learned", [])))
    leave(route)
    route.near(DARIN)
    route.ask_until(DARIN, ["Darin, you owe Hessa three weeks' lodging. A man who wants a good name in the city "
                            "ought to pay what he owes.",
                            "Pay Hessa what you owe her. You can't afford a sour name before you trade inside."],
                    lambda: "lodging" in stages(route, "trough_water"))
    leave(route)
    route.near(BREN)
    route.ask_until(BREN, ["Your sister's worried about you, Bren. She says you're standing double watches. Why?",
                           "Whatever it is, I can keep it quiet. What's going on with the watches?"],
                    lambda: any(e.get("secret") == "bren_covers_oren" for e in route.state.get("learned", [])))
    leave(route)
    route.near(HESSA)
    route.say(HESSA, "Hessa, Bren's been covering Oren's late watches without telling the captain. That's why "
                     "he's so tired.")
    report(route, "trough_water", "oren_debt", "darin_permit")
    return len(stages(route, "trough_water")) >= 4


def debts() -> bool:
    """Dice and Debts from Bren's ask to the debt answered, and the crossing: Darin's name in town comes clean."""
    route = Route("dice and debts")
    greet(route, BREN)
    route.say(BREN, "What's wrong with Oren, do you think?")
    leave(route)
    route.near(JORY)
    route.say(JORY, "Jory, have you seen anything odd with Oren the guard lately?")
    leave(route)
    route.near(DARIN)
    route.ask_until(DARIN, ["I hear Oren lost to you at dice. What does he owe you?",
                            "What do you mean to do about Oren's debt?"],
                    lambda: "squeeze" in stages(route, "oren_debt"))
    leave(route)
    route.near(BREN)
    route.ask_until(BREN, ["Bren, I know Oren owes Darin. Have you been covering for him?",
                           "You've been standing his watches, haven't you? I won't tell the captain."],
                    lambda: "brens_risk" in stages(route, "oren_debt"))
    leave(route)
    route.near(DARIN)
    route.ask_until(DARIN, ["Let Oren's debt go, Darin. Squeezing a gate guard will sour your name with the captain "
                            "just when your permit needs his seal.",
                            "Forgive the boy his eleven silver and you'll have a friend at the gate instead of an "
                            "enemy. What would it take?"],
                    lambda: "answered" in stages(route, "oren_debt"))
    report(route, "oren_debt", "darin_permit", "trough_water")
    note(f"  Darin's side: {sides(route, DARIN).get('oren_debt', {}).get('text', '')[:200]}")
    crossed = "clean_name" in stages(route, "darin_permit")
    return len(stages(route, "oren_debt")) >= 4 and crossed


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
