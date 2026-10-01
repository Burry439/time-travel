"""Live check of people passing things on (D-54): someone arrives to tell someone something; the real voice writes
both lines and picks what the listener does, from the options code built.

    backend/.venv/Scripts/python.exe evals/run_hearing_live.py [--runs 2]

Checks: both lines present, the move is one of the listener's options, and the listener's words don't promise a
visit the move doesn't make. Prints everything for reading. Costs well under a cent.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import cast  # noqa: E402
import village  # noqa: E402
from ai import config, voice  # noqa: E402

CASES = [
    ("npc_jory_venn", "npc_kade_east", "The stranger made fire from a bent nail, a flint and dry grass, right in front "
                                        "of me, and treated my burnt arm too."),
    ("npc_mara_venn", "npc_kade_east", "There's a stranger at the smithy who just dressed Jory's burn, and did it well. "
                                        "You were asking after anyone who can hold a weapon."),
    ("npc_hessa_marr", "npc_roderic_vale", "That stranger took Tomas's coil of rope from his yard without asking."),
]
GOING = re.compile(r"\b(i'?ll|i will|let'?s|i'm going to)\s+(go|come|see|walk|head|have a look)\b", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}': add OPENAI_API_KEY to backend/.env first.")
        return 1
    failures = total = 0
    for teller_id, listener_id, message in CASES:
        for run in range(args.runs):
            state = app.initial_state({"id": "hearlive", "mode": "developer", "seed_version": app.SEED_VERSION,
                                       "geometry_version": app.GEOMETRY_VERSION})
            teller, listener = cast.find(state["npcs"], teller_id), cast.find(state["npcs"], listener_id)
            context = village.hearing_context(state, listener, teller, message)
            call, result = voice.hearing(context, village.fallback_hearing(listener, teller, message))
            problems = []
            if call.status != "ok":
                problems.append(f"voice failed: {call.error}")
            if result["move"] not in context["listener_options"]:
                problems.append(f"move {result['move']} was not offered")
            if GOING.search(result["listener_line"]) and result["move"] == "carry_on":
                problems.append("says they'll go, but carries on")
            total += 1
            failures += bool(problems)
            print(f"{'PASS' if not problems else 'FAIL'}  {teller['name']} → {listener['name']}  [{result['move']}]  "
                  f"{call.latency_ms} ms")
            print(f"      {teller['name']}: {result['teller_line']}")
            print(f"      {listener['name']}: {result['listener_line']}")
            for problem in problems:
                print(f"      - {problem}")
    print(f"{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # The reports quote words; a Windows console would refuse them.
    raise SystemExit(main())
