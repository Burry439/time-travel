"""Find people who said they'd do something the game never had them do (D-51).

Scans every conversation line in the saved traces (data/demo.sqlite3, table mind_traces) for promises of a later
errand ("I'll go and tell the captain", "I'll ask Tomas", "I'll fetch it") and reports those whose move carried
nothing out. Run from the repository root:

    backend/.venv/Scripts/python tools/audit_promises.py [--run RUN_ID] [--limit 40]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMISE = re.compile(
    r"\b(i'?ll|i will|i'm going to|let me|i shall|i can go)\s+(go|run|head|walk|tell|ask|speak|talk|have a word|"
    r"fetch|bring|get|send|find|see|put in a word|mention|let \w+ know|pass)\b", re.IGNORECASE)
CARRIES_OUT = {"vouch", "call_guard", "refer", "lend", "give", "offer", "go_tell", "fetch", "accept_trade",
               "take_back", "seize", "attack", "admit", "stop_fighting"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=None)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    connection = sqlite3.connect(ROOT / "data" / "demo.sqlite3")
    query = "SELECT run_id, event_seq, npc_id, trace_json FROM mind_traces"
    rows = connection.execute(query + (" WHERE run_id=?" if args.run else ""), (args.run,) if args.run else ())
    lines = kept = 0
    broken, by_move = [], Counter()
    for run_id, seq, npc_id, blob in rows:
        trace = json.loads(blob)
        if trace.get("kind") != "talk" or not trace.get("reply"):
            continue
        lines += 1
        if not PROMISE.search(trace["reply"]):
            continue
        act = str(trace.get("action") or "answer").split(":")[0]
        if act in CARRIES_OUT:
            kept += 1
            continue
        by_move[act] += 1
        broken.append((run_id[:8], seq, npc_id, act, trace.get("voice_move"), trace["reply"]))
    print(f"{lines} lines; {kept + len(broken)} promise an errand; {kept} carried out; {len(broken)} not "
          f"(by the move code applied: {dict(by_move)})")
    for run, seq, npc, act, proposed, reply in broken[-args.limit:]:
        print(f"  {run} #{seq} {npc[4:]:<14} applied={act:<10} voice={proposed!s:<18} {reply[:150]}")


if __name__ == "__main__":
    main()
