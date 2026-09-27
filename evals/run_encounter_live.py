"""Live encounters with the real judge, Jev and voice: a fight at the smithy and a halt at the gate.

    backend/.venv/Scripts/python.exe evals/run_encounter_live.py

Temporary database; no sprites painted. Prints each round (what everyone did at the same moment)
and how long rounds took. Writes a transcript to evals/results/.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "backend"))

import run_routes_live as routes  # noqa: E402  (shares the temporary database and helpers)

log = routes.log
note = routes.note
timings: list[float] = []


def act(route: routes.Route, kind: str, text: str = "", target: str | None = None) -> dict:
    started = time.perf_counter()
    body = {"kind": kind, "text": text, "expected_version": route.state["event_seq"], "request_id": f"r{time.time_ns()}"}
    if target:
        body["target_id"] = target
    reply = routes.http.post(f"/runs/{route.run}/encounter/act", json=body)
    took = time.perf_counter() - started
    if reply.status_code != 200:
        note(f"  !! {reply.status_code} {reply.json().get('detail')}")
        return {}
    timings.append(took)
    data = reply.json()
    route.state = data["state"]
    shown = data["round"]
    note(f"  ROUND {shown['round']} — you: {kind} {('“' + text + '”') if text else ''}  ({took:.1f} s)")
    for entry in shown["entries"]:
        note(f"    · {entry['text']}")
    if shown.get("ended"):
        note("    (the encounter is over)")
    return shown


def wait_for_encounter(route: routes.Route, seconds: int = 90) -> bool:
    return route.settle(lambda: bool(route.state.get("encounter")), seconds)


def smithy_fight() -> None:
    route = routes.Route("fight at the smithy")
    route.near("npc_jory_venn")
    route.attempt("shove Jory hard")
    if not wait_for_encounter(route):
        note("  (nobody came to face the stranger)")
        return
    current = route.state["encounter"]
    note(f"  Encounter: {current['reason']} with {current['participants']}")
    act(route, "say", "I'm sorry! I didn't mean it. I'll go.")
    if route.state.get("encounter"):
        act(route, "wait")
    if route.state.get("encounter"):
        act(route, "leave")
    note(f"  Player: {route.state['player'].get('health', 100)} health, alive={route.state['player']['alive']}")


def gate_halt() -> None:
    route = routes.Route("halted at the gate")
    route.walk(48, 16)
    if not wait_for_encounter(route, 40):
        note("  (no guard came)")
        return
    guard = route.state["encounter"]["participants"][0]
    note(f"  Encounter: {route.state['encounter']['reason']} with {guard}")
    note(f"    · {route.state['encounter']['log'][0]['text']}")
    act(route, "say", "Good day. I'm Ash, a traveller looking for honest work in the city.")
    if route.state.get("encounter"):
        act(route, "say", "Who should I speak to about getting in?")
    if route.state.get("encounter"):
        act(route, "leave")


if __name__ == "__main__":
    smithy_fight()
    gate_halt()
    if timings:
        note(f"\nRounds: {len(timings)} · median {sorted(timings)[len(timings) // 2]:.1f} s · max {max(timings):.1f} s")
    out = ROOT / "evals" / "results" / f"encounters_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    out.write_text("\n".join(log), encoding="utf-8")
    print(f"Transcript: {out.relative_to(ROOT)}")
