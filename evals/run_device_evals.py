"""Live evaluation of the device (D-50): the real voice model answering the stranger's questions.

    backend/.venv/Scripts/python.exe evals/run_device_evals.py [--runs 2] [--case shield_key ...]

Needs OPENAI_API_KEY in backend/.env. A fraction of a cent per question. Writes evals/results/device_*.json.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import tutorial  # noqa: E402
from ai import config, voice  # noqa: E402


def state_for(case: dict) -> dict:
    state = app.initial_state({"id": "deviceval", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION, "scenario": "tutorial"})
    if case["step"] is None:
        state["tutorial"]["done"] = True
        state["objective"] = "Get inside the city"
    else:
        state["tutorial"]["step"] = next(i for i, s in enumerate(tutorial.STEPS) if s["id"] == case["step"])
    if case.get("attempt"):
        state["journal"].append({"kind": "craft", **case["attempt"]})
    return state


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--case", nargs="*")
    args = parser.parse_args(argv)
    if config.mode() != "live":
        print("Add OPENAI_API_KEY to backend/.env.")
        return 1
    cases = [c for c in json.loads((ROOT / "evals" / "device_cases.json").read_text(encoding="utf-8"))["cases"]
             if not args.case or c["id"] in args.case]
    report, failures, latencies = [], 0, []
    for case in cases:
        for _ in range(args.runs):
            state = state_for(case)
            call = voice.device(tutorial.device_context(state, case["question"]), tutorial.fallback_answer(state))
            text = call.text
            lower = f" {text.lower()} ".replace("’", "'")  # Curly apostrophes count as straight ones.
            problems = []
            if call.status != "ok":
                problems.append(f"voice {call.status}: {call.error}")
            if case.get("must_any") and not any(w.lower() in lower for w in case["must_any"]):
                problems.append(f"said none of {case['must_any']}")
            for word in case.get("must_not", []):  # Whole words: "AI" is not in "repairs".
                if re.search(rf"(?<![a-z]){re.escape(word.lower())}(?![a-z])", lower):
                    problems.append(f"said '{word}'")
            if sentences(text) > 3:
                problems.append(f"{sentences(text)} sentences")
            latencies.append(call.latency_ms)
            failures += bool(problems)
            report.append({"case": case["id"], "ok": not problems, "problems": problems, "answer": text,
                           "latency_ms": call.latency_ms})
            print(f"{'PASS' if not problems else 'FAIL'}  {case['id']:24} {text[:150]}")
            for problem in problems:
                print(f"      - {problem}")
    if latencies:
        print(f"\n{len(report) - failures}/{len(report)} passed · median {statistics.median(latencies):.0f} ms")
    out = ROOT / "evals" / "results" / f"device_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
