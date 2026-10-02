"""Live check of story beats (D-59): does a person answer what the stranger actually said, and bring up what their
story needs in that same reply? Found by the user's first play of "A cup of water": asked how she was, Wenna said
"fine", and then a scripted line asked for water.

    backend/.venv/Scripts/python.exe evals/run_story_beats.py [--level cup_of_water ...]

Every training level's talk steps that end with someone's authored lines are reached on a temporary database (the
steps before are skipped) and opened with several different first lines: a greeting, small talk, a question about
them, an offer of help, being lost. A step that waits for particular words (said_to) is opened with its suggested
words. Each reply is scored by what was still left to say after it (beats.left_to_say, said as written):
- carried: nothing; the reply got it all across;
- follow-on: only the tail it didn't reach ("Fill it for me, would you?");
- whole line: the reply didn't take the beat up, so the authored line followed it in full.
Scored for the person addressed; anyone else's lines are printed (someone who didn't speak says theirs as written).
Read the replies too: whether each answers its opener is a judgment this eval prints but doesn't make. Writes
evals/results/story_beats_*.json. A few cents a run (one voice call a reply).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import cast  # noqa: E402
import content  # noqa: E402
import paths  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

app.store.DB_PATH = Path(tempfile.mkdtemp()) / "beats.sqlite3"
app.attempts._generate_asset = lambda asset_id: None  # No paintings: this is about words.
http = TestClient(app.app)
TALK = ("talked_to", "said_to")
OPENERS = ["Hello.", "Lovely day, isn't it?", "Who are you?", "Can I help with anything?", "I'm lost. Where am I?"]


def post(state: dict, path: str, body: dict) -> dict:
    body = {**body, "expected_version": state["event_seq"], "request_id": f"{path}-{time.time_ns()}"}
    reply = http.post(f"/runs/{state['run_id']}/{path}", json=body)
    assert reply.status_code == 200, (path, reply.status_code, reply.text[:300])
    return reply.json()["state"]


def cases(only: list[str]) -> list[tuple[str, dict, str, list[str]]]:
    """(level, step, person, openers) for each talk step whose completion has someone's authored lines."""
    found = []
    for level in content.LEVELS.values():
        if level.get("track") not in ("basic", "advanced") or (only and level["id"] not in only):
            continue
        for step in level.get("steps", []):
            lines = [e for e in step.get("on_done", []) if e["kind"] == "npc_says"]
            if step["check"]["kind"] in TALK and lines:
                person = step["check"].get("npc") or lines[0]["npc"]
                words = OPENERS if step["check"]["kind"] == "talked_to" else [(step.get("suggest") or {})["text"]]
                found.append((level["id"], step, person, words))
    return found


def to_step(level: str, step_id: str) -> dict:
    state = http.post("/runs", json={"mode": "developer", "scenario": level}).json()
    steps = content.LEVELS[level]["steps"]
    for _ in range(len(steps) + 1):
        current = steps[state["tutorial"]["step"]]["id"]
        state = http.post(f"/runs/{state['run_id']}/tutorial/read", json={"step": state["tutorial"]["step"]}).json()
        state = state["state"]
        if current == step_id:
            return state
        if steps[state["tutorial"]["step"]]["id"] == current:  # Its check didn't hold on reading: skip it.
            state = http.post(f"/runs/{state['run_id']}/tutorial/skip").json()["state"]
    raise RuntimeError(f"{level}: never reached {step_id}")


def walk_to(state: dict, npc_id: str) -> dict:
    person = cast.find(state["npcs"], npc_id)
    start = (state["player"]["x"], state["player"]["y"])
    previous, steps = paths.bfs(start, paths.grid(state), 400)
    goal = min(steps, key=lambda c: (abs(c[0] - person["x"]) + abs(c[1] - person["y"] - 1), steps[c]))
    route = []
    while goal != start:
        route.append(list(goal))
        goal = previous[goal]
    for i in range(0, len(route), 20):
        state = post(state, "move", {"cells": route[::-1][i : i + 20]})
    return state


def play(level: str, step: dict, npc_id: str, opener: str) -> dict:
    state = walk_to(to_step(level, step["id"]), npc_id)
    before = len(state["journal"])
    state = post(state, "say", {"npc_id": npc_id, "text": opener})
    state = post(state, "explore", {"elapsed_ms": 1000})
    replies, authored = [], []
    for entry in state["journal"][before:]:
        if entry.get("kind") == "talk":
            replies.append(f"{entry['npc_id'][4:]}: {entry.get('reply')}")
        elif entry.get("category") == "heard":
            authored.append(entry["reason"])
    # Scored for the person addressed: someone else's line (one who didn't speak in that round) is said as written.
    lines = {e["npc"]: e["text"] for e in step["on_done"] if e["kind"] == "npc_says"}
    scored = npc_id if npc_id in lines else next(iter(lines))
    name = cast.find(state["npcs"], scored)["name"]
    theirs = [a for a in authored if a.startswith(f"{name}: ")]
    verdict = "carried" if not theirs else "whole line" if f"{name}: “{lines[scored]}”" in theirs else "follow-on"
    return {
        "level": level,
        "step": step["id"],
        "opener": opener,
        "replies": replies,
        "then": authored,
        "verdict": verdict,
        "moved_on": state["tutorial"]["step"] != content.LEVELS[level]["steps"].index(step),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", nargs="*", default=[])
    results = []
    for level, step, npc_id, openers in cases(parser.parse_args().level):
        print(f"\n=== {level} / {step['id']} ({npc_id[4:]})")
        for opener in openers:
            result = play(level, step, npc_id, opener)
            results.append(result)
            print(f"  YOU > {opener}")
            for line in result["replies"]:
                print(f"    {line}")
            for line in result["then"]:
                print(f"    then (authored): {line}")
            print(f"    -> {result['verdict']}{'' if result['moved_on'] else '  (the step did not move on)'}")
    counts = {v: sum(r["verdict"] == v for r in results) for v in ("carried", "follow-on", "whole line")}
    print(f"\nSTORY BEATS: {len(results)} replies: " + ", ".join(f"{v} {n}" for v, n in counts.items()))
    out = ROOT / "evals" / "results" / f"story_beats_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({"counts": counts, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
