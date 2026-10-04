"""Live playthrough of the three routes into the city with the real judge, decider and voice.

    backend/.venv/Scripts/python.exe evals/run_routes_live.py [sponsor] [business] [value]

Plays each route as a player would type it (with a few rephrasings when someone isn't ready yet),
on a temporary database, and reports whether the stranger got in, how, and what it cost. Sprites
are not painted. Costs a few cents. Writes a transcript to evals/results/.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import cast  # noqa: E402
import paths  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

app.store.DB_PATH = Path(tempfile.mkdtemp()) / "routes.sqlite3"
app.attempts.generate_asset = lambda asset_id: None  # No paintings: this is about the route, not the art.
http = TestClient(app.app)
log: list[str] = []


def note(text: str) -> None:
    print(text)
    log.append(text)


class Route:
    def __init__(self, name: str):
        self.name = name
        self.state = http.post("/runs", json={"mode": "developer"}).json()
        note(f"\n=== {name.upper()} ===")

    @property
    def run(self) -> str:
        return self.state["run_id"]

    def person(self, npc_id: str) -> dict:
        return cast.find(self.state["npcs"], npc_id)

    def walk(self, x: int, y: int) -> None:
        start = (self.state["player"]["x"], self.state["player"]["y"])
        previous, steps = paths.bfs(start, paths.grid(self.state), 250)
        goal = min(steps, key=lambda c: (abs(c[0] - x) + abs(c[1] - max(y, 9)), steps[c]))
        path = []
        while goal != start:
            path.append(list(goal))
            goal = previous[goal]
        path = path[::-1] + ([[x, row] for row in range(8, y - 1, -1)] if y < 9 else [])
        for i in range(0, len(path), 20):
            reply = http.post(f"/runs/{self.run}/move", json={"cells": path[i:i + 20], "request_id": f"w{time.time_ns()}",
                                                              "expected_version": self.state["event_seq"]})
            self.state = reply.json().get("state", self.state)
            if reply.status_code != 200:
                note(f"  (walk stopped: {reply.json().get('detail')})")
                return

    def near(self, npc_id: str) -> None:
        person = self.person(npc_id)
        self.walk(person["x"], person["y"] + 1)

    def say(self, npc_id: str, text: str) -> str | None:
        reply = http.post(f"/runs/{self.run}/say", json={"npc_id": npc_id, "text": text,
                                                         "expected_version": self.state["event_seq"],
                                                         "request_id": f"s{time.time_ns()}"})
        if reply.status_code != 200:
            note(f"  YOU → {npc_id[4:]}: {text}\n    !! {reply.status_code} {reply.json().get('detail')}")
            if reply.status_code == 409 and "cannot_talk" in json.dumps(reply.json()):
                self.settle(lambda: False, 3)
            self.state = http.get(f"/runs/{self.run}").json()
            return None
        body = reply.json()
        self.state, trace = body["state"], body["trace"]
        beliefs = {k: round(v["noul"], 2) for k, v in trace["call"]["answers"].items()
                   if k in ("threat", "reason", "accepts", "done") and "noul" in v}
        note(f"  YOU → {self.person(npc_id)['name']}: {text}\n    [{trace['action']}] “{trace['reply']}”  "
             f"(person {trace['voice'].get('latency_ms', 0)} ms)"
             + (f" beliefs {beliefs}" if beliefs else ""))
        return trace["action"]

    def ask_until(self, npc_id: str, lines: list[str], done) -> bool:
        for line in lines:
            self.near(npc_id)
            self.say(npc_id, line)
            if done():
                return True
        return False

    def attempt(self, text: str) -> dict:
        reply = http.post(f"/runs/{self.run}/craft", json={"text": text, "selected_ids": [],
                                                           "expected_version": self.state["event_seq"],
                                                           "request_id": f"c{time.time_ns()}"})
        body = reply.json()
        self.state = body.get("state", self.state)
        entry = self.state["last_action"]
        note(f"  TRY: {text}\n    [{entry['category']}] {entry['reason']}")
        return entry

    def settle(self, until, seconds: int = 60) -> bool:
        """Let the clock run and people think (the real decider) until the condition holds."""
        for _ in range(seconds * 2):
            if until():
                return True
            path = "think" if self.state.get("pending_minds") else "explore"
            body = {"expected_version": self.state["event_seq"], "request_id": f"t{time.time_ns()}"}
            if path == "explore":
                body["elapsed_ms"] = 1000
            reply = http.post(f"/runs/{self.run}/{path}", json=body)
            if reply.status_code == 200:
                self.state = reply.json()["state"]
                for entry in self.state["journal"][-3:]:
                    if entry.get("kind") == "npc" and entry.get("_seen") is None:
                        pass
        return until()

    def deal(self, npc_id: str, status: str) -> bool:
        return any(a.get("issuer") == npc_id and a["status"] == status for a in self.state["agreements"].values())

    def enter(self, pitch: list[str]) -> bool:
        roderic = "npc_roderic_vale"
        if not self.ask_until(roderic, pitch, lambda: bool(self.state.get("admitted"))):
            note("  ✗ Roderic did not admit the stranger.")
            return False
        note(f"  Admitted because: {self.state['admitted']['because']}")
        self.walk(48, 3)
        note(f"  {'✓ INSIDE THE CITY' if self.state['inside_city'] else '✗ could not walk in'}")
        return self.state["inside_city"]


def sponsor() -> bool:
    route = Route("sponsor: Hessa's water")
    route.walk(45, 52)
    route.attempt("pick up the dried gourd")
    hessa = "npc_hessa_marr"
    if not route.ask_until(hessa, ["Good day! I'm Ash, a traveller. Your yard looks busy. Can I help with anything?",
                                   "I'm happy to work for my keep. Is there any job I could do for you?",
                                   "I mean it: fetching, carrying, anything that needs doing."],
                           lambda: route.deal(hessa, "proposed")):
        note("  ✗ Hessa never offered a deal.")
        return False
    route.ask_until(hessa, ["Gladly. I'll bring you water from the trough right away.", "Yes, it's a deal."],
                    lambda: route.deal(hessa, "accepted"))
    route.attempt("fill the gourd with water from the trough and hand it to Hessa")
    route.settle(lambda: not route.state.get("pending_minds"), 20)
    if not route.ask_until(hessa, ["There you are: a gourd full of water for your kitchen.",
                                   "That's the water you asked for, fresh from the trough."],
                           lambda: route.deal(hessa, "fulfilled")):
        note("  ✗ Hessa did not count the deal as done.")
        return False
    route.settle(lambda: any(m["kind"] == "vouch" for m in cast.mind(route.person("npc_roderic_vale"))["memories"]), 120)
    return route.enter(["Captain, Hessa the innkeeper has spoken for me. I'd like to enter the city to find honest work.",
                        "My name is Ash. I carried water for Hessa and I'll work honestly for anyone in the city."])


def business() -> bool:
    route = Route("business: Darin hires you")
    route.walk(51, 65)
    route.attempt("pick up the hollow reeds and the flint shard")
    route.attempt("cut a short length of reed with the flint and carve a notch to make a whistle")
    darin = "npc_darin_ko"
    if not route.ask_until(darin, ["Good day, sir. I'm Ash, a traveller with a knack for making useful little things.",
                                   "Would a merchant like you have use for someone who makes new things to sell?",
                                   "If I showed you something new you could sell, would you take me on?"],
                           lambda: route.deal(darin, "proposed")):
        note("  ✗ Darin never offered a deal.")
        return False
    route.ask_until(darin, ["Agreed. Let me show you.", "Yes, deal."], lambda: route.deal(darin, "accepted"))
    route.near(darin)
    route.attempt("blow the reed whistle for Darin to show him how loud and clear it is")
    if not route.ask_until(darin, ["There: a whistle anyone could carry, made from a reed. Travellers and herders would buy those.",
                                   "I can make dozens of them from reeds. Worth selling, wouldn't you say?"],
                           lambda: route.deal(darin, "fulfilled")):
        note("  ✗ Darin did not count the deal as done.")
        return False
    route.settle(lambda: any(m["kind"] == "vouch" for m in cast.mind(route.person("npc_roderic_vale"))["memories"]), 150)
    return route.enter(["Captain, I'm Darin the merchant's hired hand; he's taking me in under his trade permit.",
                        "My name is Ash. I work for Darin now and I'll keep to honest trade."])


def value() -> bool:
    route = Route("value: a compass for the patrols")
    darin = "npc_darin_ko"
    # Words alone won't move a shrewd merchant: show him something first, then ask.
    route.walk(51, 65)
    route.attempt("pick up the hollow reeds and the flint shard")
    route.attempt("cut a short length of reed with the flint and carve a notch to make a whistle")
    route.near(darin)
    route.attempt("blow the reed whistle for Darin to show him what a stranger's knack can make")
    if not route.ask_until(darin, ["Good day. I'm Ash, a traveller who knows a trick or two with iron. Do you have "
                                   "a stone that pulls iron? I hear it's of no use to you.",
                                   "Lend it to me for an hour and I'll show you how to turn it into a direction-finder "
                                   "you could sell. The idea is yours to trade.",
                                   "A direction-finder: stroke an iron needle on your stone, float it on water, and "
                                   "it swings round to point the same way every time. Caravans lost in fog would pay "
                                   "well for one.",
                                   "I'll make it right here in front of you, and you keep the stone and the idea. You "
                                   "lose nothing."],
                           lambda: route.state["objects"]["lodestone_darin"].get("lent_to") == "player"):
        note("  ✗ Darin would not lend the lodestone.")
        return False
    route.attempt("pick up the lodestone")
    route.walk(27, 28)
    route.attempt("pick up the bent iron nail and stroke it many times in one direction with the lodestone to magnetise it")
    route.near(darin)
    route.attempt("give the lodestone back to Darin")  # As promised; and it would pull the needle off course.
    route.walk(52, 64)
    route.attempt("pick up the strip of bark")
    route.walk(50, 17)
    route.settle(lambda: False, 8)  # A guard may come to halt the stranger.
    route.near("npc_roderic_vale")
    route.walk(50, 17)
    route.attempt("float the magnetised nail on the strip of bark in the gate trough and show Captain Roderic that it "
                  "always swings back to point the same way, even when I turn it")
    if route.enter(["Captain, that needle always points the same way. With one, your patrols could hold their "
                    "heading on the moor road in fog."]):
        return True
    route.near("npc_roderic_vale")
    route.attempt("give Captain Roderic the magnetised nail and the strip of bark so his patrols can use it")
    return route.enter(["Keep it, captain: float it on water whenever the fog comes down and it shows the same "
                        "heading every time. My name is Ash, and I can make more for the garrison."])


def act(route: Route, kind: str, text: str = "", target: str | None = None) -> dict:
    """The stranger's part of an encounter round."""
    body = {"kind": kind, "text": text, "expected_version": route.state["event_seq"], "request_id": f"r{time.time_ns()}"}
    if target:
        body["target_id"] = target
    reply = http.post(f"/runs/{route.run}/encounter/act", json=body)
    if reply.status_code != 200:
        note(f"  !! {reply.status_code} {reply.json().get('detail')}")
        return {}
    route.state = reply.json()["state"]
    shown = reply.json()["round"]
    note(f"  ROUND ({kind}{': ' + text if text else ''})")
    for entry in shown["entries"]:
        note(f"    · {entry['text']}")
    return shown


def lent(route: Route, *ids: str) -> bool:
    return all(route.state["objects"][i].get("lent_to") == "player" for i in ids)


def beam() -> bool:
    route = Route("beam: raise Tomas's gate beam")
    tomas = "npc_tomas_reed"
    if not route.ask_until(tomas, ["Good day, I'm Ash. That gate beam looks like trouble. I know how to lift heavy "
                                   "things safely with a rope and a ladder.",
                                   "I could get it up into the brackets for you, if you'll let me.",
                                   "Honestly, I've done this before. Rope over the bracket, ladder to guide it."],
                           lambda: route.deal(tomas, "proposed") or route.deal(tomas, "accepted")):
        note("  ✗ Tomas never offered the job.")
        return False
    route.ask_until(tomas, ["Agreed, I'll get it up for you.", "Yes, it's a deal."],
                    lambda: route.deal(tomas, "accepted"))
    wanted = ("wood_tomas", "fulcrum_tomas", "trestles_gate", "rope_tomas", "ladder_tomas")
    asks = ["To do it safely I'll lever it up in stages: may I borrow your plank and fulcrum stone?",
            "And your trestles by the gate, to rest it on between lifts?",
            "The rope and ladder too, to guide it the last bit into the brackets?",
            "Just the rest of what I asked for, and it all comes back to you.",
            "The ladder, please.", "The trestles, please.", "The rope, please."]
    route.ask_until(tomas, asks, lambda: lent(route, *wanted))
    aids = [i for i in wanted if lent(route, i) and i != "trestles_gate"]
    if not (lent(route, "wood_tomas", "fulcrum_tomas") or lent(route, "rope_tomas", "ladder_tomas")):
        note("  ✗ Tomas didn't lend enough to lift with.")
        return False
    route.attempt("pick up the " + " and the ".join(route.state["objects"][i]["name"] for i in aids))
    route.walk(54, 12)
    route.settle(lambda: bool(route.state.get("encounter")), 6)  # A guard may come to ask what's going on.
    if route.state.get("encounter"):
        act(route, "say", "I'm working for Tomas the carpenter: I'm here to raise the new gate beam.")
    if lent(route, "wood_tomas", "fulcrum_tomas"):
        method = ("lever each end of the gate beam up in turn using the plank over the fulcrum stone, and after each "
                  "lift crib it up: first on the empty crates, then on the trestles set up beside it, stacking higher "
                  "each time, until it is at chest height; then " +
                  ("loop the rope over the iron brackets and, from the ladder, haul and guide the beam up the last "
                   "stretch into them" if lent(route, "rope_tomas", "ladder_tomas") else
                   "climb up and ease each end up the last stretch into the brackets"))
        if lent(route, "ladder_tomas"):
            method += ", guiding it from the ladder"
    else:
        method = ("loop the rope over the iron brackets, tie it to the beam, and raise one end at a time, resting it "
                  "on the ladder rungs between pulls, then guide it into the brackets")
    route.attempt(method)
    if route.state.get("encounter"):
        act(route, "leave")
    if not route.state["objects"]["gate_beam"].get("installed_in"):
        note("  ✗ The beam didn't go up.")
        return False
    note("  (the beam is up in its brackets)")
    if not route.ask_until(tomas, ["The beam is up in its brackets, safe and sound.",
                                   "Go and look: the gate beam is in place."],
                           lambda: route.deal(tomas, "fulfilled")):
        note("  ✗ Tomas did not count the deal as done.")
        return False
    route.settle(lambda: any(m["kind"] == "vouch" for m in cast.mind(route.person("npc_roderic_vale"))["memories"]), 150)
    return route.enter(["Captain, Tomas has spoken for me: I raised the new gate beam into its brackets.",
                        "My name is Ash. I'd work honestly in the city."])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # The reports quote words; a Windows console would refuse them.
    wanted = sys.argv[1:] or ["sponsor", "business", "value", "beam"]
    started = time.perf_counter()
    results = {name: globals()[name]() for name in wanted}
    note(f"\nRESULTS: {results} in {time.perf_counter() - started:.0f} s")
    out = ROOT / "evals" / "results" / f"routes_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    out.write_text("\n".join(log), encoding="utf-8")
    print(f"Transcript: {out.relative_to(ROOT)}")
