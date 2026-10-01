"""Live run of the village on its own (GDD D-37): ten simulated minutes with the real decider (the language model).

    backend/.venv/Scripts/python.exe evals/run_world_live.py [--minutes 10]

The stranger walks up to the inn and steals Hessa's bucket, then stands still while the village goes on.
Reports what people chose to do, who met whom and what they talked about, how far the theft travelled
(did it reach a guard?), and the calls and cost per simulated minute. Uses a temporary database.
About five cents. Writes evals/results/world_*.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import cast  # noqa: E402
from ai import decider  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=10)
    args = parser.parse_args(argv)
    if decider.mode() != "llm":
        print("Needs OPENAI_API_KEY in backend/.env.")
        return 1
    app.store.DB_PATH = Path(tempfile.mkdtemp()) / "world.sqlite3"
    http = TestClient(app.app)
    seq = [0]

    def post(state: dict, path: str, body: dict) -> dict:
        seq[0] += 1
        reply = http.post(f"/runs/{state['run_id']}/{path}", json={
            **body, "expected_version": state["event_seq"], "request_id": f"{path}-{seq[0]}"})
        data = reply.json()
        return data.get("state") or data.get("detail", {}).get("state") or state, data

    state = http.post("/runs", json={"mode": "developer"}).json()
    state, _ = post(state, "move", {"cells": [[48, y] for y in range(67, 55, -1)]})
    state, _ = post(state, "move", {"cells": [[x, 55] for x in range(47, 38, -1)]})
    state, taken = post(state, "quick", {"verb": "take", "object_id": "bucket_hessa"})
    print("Theft:", state["last_action"]["reason"], "| witnesses:",
          [p["npc_id"] for p in taken.get("state", {}).get("pending_minds", [])])
    decisions, started, thinks = [], time.time(), 0
    confronted = []
    for second in range(args.minutes * 60):
        if state.get("encounter"):  # Someone came up to the stranger: note it, and walk away so time goes on.
            confronted.append([e["text"] for e in state["encounter"].get("log", [])][:3])
            state, _ = post(state, "encounter/act", {"kind": "leave"})
            continue
        state, _ = post(state, "explore", {"elapsed_ms": 1000})
        while state.get("pending_minds") and thinks < 400:
            thinks += 1
            state, data = post(state, "think", {})
            decisions += data.get("decisions", [])
            if not data.get("decisions"):
                break
    agendas = Counter(d.get("agenda", "?").split(":")[0] for d in decisions if d["kind"] == "agenda" and not d["skipped"])
    meetings = [d for d in decisions if d["kind"] == "meet" and not d["skipped"]]
    topics = Counter(d["topic"].split(":")[0] for d in meetings)
    who_knows = [n["name"] for n in state["npcs"] if any(m.get("kind") == "theft" for m in cast.mind(n)["memories"])]
    guards_know = [n for n in who_knows if cast.card(cast.find(state["npcs"], next(
        x["id"] for x in state["npcs"] if x["name"] == n))).get("guard")]
    calls = http.get(f"/runs/{state['run_id']}/traces?limit=10").json().get("model_calls", [])
    decider_calls = [c for c in calls if c["role"] == "decider"]
    print(f"\n{args.minutes} simulated minutes in {time.time() - started:.0f} s real time · {thinks} think requests")
    print("Agenda choices:", dict(agendas))
    print(f"Meetings: {len(meetings)} · topics {dict(topics)} · voiced {sum(m['voiced'] for m in meetings)}")
    for m in meetings[:8]:
        print(f"  {m['npc_id'][4:]:12} → {m['with'][4:]:12} {m['topic']:24} {m['reaction']}: {m['about'][:90]}")
    print("Knows about the theft:", who_knows, "| guards among them:", guards_know)
    for lines in confronted:
        print("Came up to the stranger:", " / ".join(lines))
    print("Moods now:", {n["name"]: cast.mind(n).get("mood") for n in state["npcs"]})
    print("Doing now:", {n["name"]: cast.mind(n).get("doing") for n in state["npcs"]})
    out = ROOT / "evals" / "results" / f"world_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({"agendas": agendas, "meetings": meetings, "who_knows": who_knows,
                               "decider_calls_last_page": len(decider_calls), "thinks": thinks,
                               "decisions": decisions}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
