"""Live check of the world's vocabulary (D-65): deeds the judge allows must change the world, or be refused honestly.

    backend/.venv/Scripts/python.exe evals/run_deeds_live.py [case ...]

The user's own attempts that once "succeeded" and changed nothing come first, then deeds for the families built so
far (bodies, writing, touch). Each case plays from a fresh journey on a temporary database, through the same
/act route the game uses, with the real judge and voices and no paintings, and checks the world afterwards. A
case passes when the world changed as narrated (and the people touched remember it), or when the deed was refused
honestly (failed, blocked) where refusing is right. A few cents a case. Writes evals/results/deeds_*.txt.
"""

from __future__ import annotations

import sys
import time

import run_routes_live as routes
from run_routes_live import ROOT, Route, note

import cast  # noqa: E402  (run_routes_live put backend on the path)


def act(route: Route, text: str, mode: str = "do") -> dict:
    """What the player types in the bar, through /act like the game."""
    body = {"text": text, "selected_ids": [], "mode": mode, "expected_version": route.state["event_seq"],
            "request_id": f"d{time.time_ns()}"}
    reply = routes.http.post(f"/runs/{route.run}/act", json=body)
    data = reply.json()
    if reply.status_code != 200:
        note(f"  DO: {text}\n    !! {reply.status_code} {str(data.get('detail'))[:200]}")
        route.state = routes.http.get(f"/runs/{route.run}").json()
        return {}
    route.state = data.get("state", route.state)
    entry = route.state.get("last_action") or {}
    if data.get("round"):
        lines = " | ".join(e.get("text", "")[:110] for e in data["round"]["entries"])
        note(f"  DO: {text}\n    [round] {lines}")
    else:
        note(f"  DO: {text}\n    [{entry.get('category')}] {entry.get('reason', '')[:220]}")
    return data


def person(route: Route, npc_id: str) -> dict:
    return cast.find(route.state["npcs"], npc_id)


def memories(route: Route, npc_id: str, word: str) -> list[dict]:
    return [m for m in (person(route, npc_id).get("mind") or {}).get("memories", []) if word in m.get("summary", "").lower()]


def refused(route: Route) -> bool:
    return (route.state.get("last_action") or {}).get("category") in ("failed", "blocked")


def chalk_slip() -> bool:
    route = Route("chalk a permission slip on bark")
    route.walk(58, 31)
    route.attempt("pick up the piece of chalk")
    route.walk(52, 64)
    act(route, "use the chalk to write a permission slip on the strip of bark saying I can enter the city")
    writing = [a for a in route.state["objects"]["bark_a"].get("attributes", []) if a["name"] in ("writing", "mark")]
    note(f"  bark: {writing}")
    return bool(writing)


def kiss_hessa() -> bool:
    route = Route("kiss Hessa")
    route.near("npc_hessa_marr")
    act(route, "give Hessa a kiss on the lips")
    remembered = memories(route, "npc_hessa_marr", "kiss")
    note(f"  Hessa remembers: {[m['summary'][:100] for m in remembered]}")
    return bool(remembered)


def water_on_bren() -> bool:
    route = Route("dump water on Bren")
    route.walk(45, 53)
    route.attempt("pick up the dried gourd")
    route.walk(36, 53)
    route.attempt("fill the gourd with water from the trough")
    route.near("npc_bren_marr")
    act(route, "dump the water on Bren's head")
    bren = person(route, "npc_bren_marr")
    wet = bren.get("states", []) or [m for m in (bren.get("mind") or {}).get("memories", []) if "water" in m.get("summary", "").lower()]
    note(f"  Bren: states {bren.get('states')} | remembers {[m['summary'][:90] for m in memories(route, 'npc_bren_marr', 'water')]}")
    return bool(wet)


def pee_in_trough() -> bool:
    route = Route("pee in the gate trough")
    route.walk(50, 17)
    act(route, "I pee into the water trough")
    trough = route.state["objects"]["trough_gate"]
    note(f"  trough: {trough.get('attributes')}")
    return bool(trough.get("attributes")) or refused(route)


def till_sundown() -> bool:
    route = Route("wait a long while")
    start = route.state["sim_time_ms"]
    act(route, "sit down by the road and wait for an hour")
    waited = (route.state["sim_time_ms"] - start) / 60000
    note(f"  minutes passed: {waited:.0f}")
    return waited >= 30


def ask_as_a_deed() -> bool:
    route = Route("ask Hessa, typed as a deed")
    route.near("npc_hessa_marr")
    data = act(route, "ask hess awhats up")
    entries = (data.get("round") or {}).get("entries", [])
    return any(e.get("who") not in ("player", None) or "Hessa" in e.get("text", "") for e in entries)


def swallow_nails() -> bool:
    route = Route("swallow nails")
    route.walk(77, 55)
    act(route, "I pick up a handful of nails and swallow them whole")
    entry = route.state.get("last_action") or {}
    hurt = entry.get("hurt_self") or route.state["player"].get("conditions")
    gone = route.state["objects"]["yard_nails"].get("holder_id") == "used"
    note(f"  hurt: {bool(hurt)} | nails used up: {gone}")
    return bool(hurt) or gone or refused(route)


def tie_up_bren() -> bool:
    route = Route("tie up an alert, armed guard")
    route.walk(77, 67)
    route.attempt("pick up the coil of hemp rope")
    route.near("npc_bren_marr")
    act(route, "tie Bren's hands behind his back with the rope")
    bren = person(route, "npc_bren_marr")
    bound = any("move" in s.get("limits", []) or "hands" in s.get("limits", []) for s in bren.get("states", []))
    note(f"  Bren states: {bren.get('states')}")
    return refused(route) or not bound or bool(memories(route, "npc_bren_marr", "rope"))


def forged_permit() -> bool:
    route = Route("show the captain a forged permit")
    route.walk(58, 31)
    route.attempt("pick up the piece of chalk")
    route.walk(90, 57)
    route.attempt("pick up the sheet of birch bark")
    act(route, "write on the birch bark in chalk: 'Let the bearer pass. By order of the city council.'")
    route.near("npc_roderic_vale")
    act(route, "show Captain Roderic the birch bark pass")
    writing = [a for a in route.state["objects"]["birchbark_a"].get("attributes", []) if a["name"] == "writing"]
    note(f"  pass: {writing}")
    return bool(writing) and not route.state.get("admitted")


CASES = {name: fn for name, fn in globals().items() if callable(fn) and fn.__module__ == __name__ and name not in ("act", "person", "memories", "refused", "main")}


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
    note(f"\nRESULTS: {sum(results.values())}/{len(results)}  " + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in results.items()))
    out = ROOT / "evals" / "results" / f"deeds_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    out.write_text("\n".join(routes.log), encoding="utf-8")
    print(f"Transcript: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
