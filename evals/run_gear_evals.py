"""Live evaluation of gear (D-49): the real judge plus the real validator and gear.hit.

    backend/.venv/Scripts/python.exe evals/run_gear_evals.py [--runs 2] [--case flint_spear ...]

Needs OPENAI_API_KEY in backend/.env. About a cent per case per run. Writes evals/results/gear_*.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import cast  # noqa: E402
import consequences  # noqa: E402
import judge_view  # noqa: E402
from ai import config, judge  # noqa: E402


def world_for(case: dict) -> dict:
    state = app.initial_state({"id": "geareval", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION})
    if "beside" in case:
        npc = cast.find(state["npcs"], case["beside"])
        state["player"].update(x=npc["x"], y=npc["y"] + 1)
    for object_id in case["carry"]:
        state["objects"][object_id].update(holder_id="player", x=state["player"]["x"], y=state["player"]["y"])
    for npc_id in case.get("facing", []):
        cast.mind(cast.find(state["npcs"], npc_id))["facing_player"] = True
    return state


def run_case(case: dict) -> dict:
    state = world_for(case)
    context = judge_view.build_context(state, case["text"], case["carry"])
    started = time.perf_counter()
    judged = judge.judge_craft(context)
    seconds = round(time.perf_counter() - started, 1)
    if judged.status != "ok":
        return {"case": case["id"], "ok": False, "problems": [f"judge {judged.status}: {judged.error}"]}
    payload, summary, after = consequences.resolve_attempt(state, "geareval", case["text"], judged.result, None, "t", 0)
    problems = []
    made = (summary.get("new_spec") or {}).get("gear") if summary.get("new_spec") else None
    if made is None and summary.get("transform"):
        made = (summary["transform"]["pieces"] or [{}])[0].get("gear")
    proposed = [s.get("new_object", {}) and (s.get("new_object") or {}).get("gear") for s in judged.result.get("steps", [])]
    if "made_class_any" in case:
        if not made or made.get("class") not in case["made_class_any"]:
            problems.append(f"made {made} (judge proposed {proposed}), wanted one of {case['made_class_any']}")
    harm = summary.get("harm") or {}
    if "result_any" in case:
        if harm.get("result") not in case["result_any"]:
            problems.append(f"result {harm.get('result')} ({harm.get('family')}, {harm.get('area')}, "
                            f"{harm.get('effective')}), wanted one of {case['result_any']}")
    if "alive" in case and "beside" in case:
        target = cast.find(after["npcs"], case["beside"])
        if target.get("alive", True) != case["alive"]:
            problems.append(f"{target['name']} {'alive' if target.get('alive', True) else 'dead'}")
    return {"case": case["id"], "ok": not problems, "problems": problems, "seconds": seconds,
            "category": summary["category"], "reason": summary["reason"], "made": made,
            "harm": {k: harm.get(k) for k in ("result", "family", "area", "effective", "conditions")} if harm else None,
            "notes": summary["notes"]}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--case", nargs="*")
    args = parser.parse_args(argv)
    if config.mode() != "live":
        print("Add OPENAI_API_KEY to backend/.env.")
        return 1
    cases = [c for c in json.loads((ROOT / "evals" / "gear_cases.json").read_text(encoding="utf-8"))["cases"]
             if not args.case or c["id"] in args.case]
    report, failures = [], 0
    for case in cases:
        for _ in range(args.runs):
            result = run_case(case)
            report.append(result)
            failures += not result["ok"]
            detail = (result.get("made") or {}).get("class") if "made_class_any" in case else \
                (result.get("harm") or {}).get("result")
            print(f"{'PASS' if result['ok'] else 'FAIL'}  {case['id']:18} {str(detail):12} {result.get('reason', '')[:110]}")
            for problem in result["problems"]:
                print(f"      - {problem}")
    print(f"\n{len(report) - failures}/{len(report)} passed")
    out = ROOT / "evals" / "results" / f"gear_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
