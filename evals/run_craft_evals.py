"""Live evaluation of the crafting judge plus the real validator.

    backend/.venv/Scripts/python.exe evals/run_craft_evals.py [--runs 3] [--case flint_spear ...]

Needs OPENAI_API_KEY in backend/.env. Costs real money (roughly a cent per case per run on gpt-6-sol).
Writes a JSON report to evals/results/ and prints a summary.
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import crafting  # noqa: E402
from ai import config, judge  # noqa: E402

PRICES_PER_MTOK = {"gpt-6-sol": (2.0, 10.0), "gpt-6-luna": (0.1, 0.5), "gpt-6-astra": (10.0, 50.0)}


def world_with(case: dict) -> dict:
    state = app.initial_state({"id": "eval", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION})
    for object_id in case["carry"]:
        state["objects"][object_id]["holder_id"] = "player"
    for object_id, fields in case.get("set", {}).items():  # e.g. water already in a bowl, and how hot it is
        state["objects"][object_id].update(fields)
        crafting.rename(state["objects"][object_id])
    if "player_at" in case:
        state["player"].update(x=case["player_at"][0], y=case["player_at"][1])
    if "beside" in case:
        npc = next(n for n in state["npcs"] if n["id"] == case["beside"])
        state["player"].update(x=npc["x"], y=npc["y"] + 1)
    return state


def check(case: dict, judged: judge.JudgeCall, verdict: dict) -> list[str]:
    problems = []
    if verdict["category"] not in case["expect"]:
        problems.append(f"category {verdict['category']} not in {case['expect']}")
    spec = verdict["new_spec"] or {}
    consumed = set(verdict["consumed_ids"])
    steps = (judged.result or {}).get("steps") or []
    objects = [st["new_object"] for st in steps if st.get("new_object")]
    proposed = {"consumes": [i for o in objects for i in o["consumes"]],
                "flags": [f for o in objects for f in o["flags"]],
                "materials": [m for o in objects for m in o["materials"]]}
    for item in case.get("must_not_consume", []):
        if item in consumed or item in proposed.get("consumes", []):
            problems.append(f"consumed {item}")
    for flag in case.get("forbid_flags", []):
        if flag in spec.get("flags", []) or flag in proposed.get("flags", []):
            problems.append(f"flag {flag} proposed")
    for material in case.get("forbid_materials", []):
        if material in spec.get("materials", []) or material in proposed.get("materials", []):
            problems.append(f"material {material} proposed")
    wanted = case.get("require_flags_any")
    if wanted and verdict["category"] == "success" and not set(wanted) & set(spec.get("flags", [])):
        problems.append(f"none of {wanted} in flags {spec.get('flags')}")
    if case.get("require_harm_result") and verdict["category"] == "success" and             (verdict.get("harm") or {}).get("result") not in case["require_harm_result"]:
        problems.append(f"harm result {(verdict.get('harm') or {}).get('result')} not in {case['require_harm_result']}")
    if case.get("require_change") and verdict["category"] == "success":
        changes = [st["change"] for st in steps if st.get("change")]
        for key, value in case["require_change"].items():
            if not any(c.get(key) == value for c in changes):
                problems.append(f"no change with {key}={value}: {changes}")
    if case.get("forbid_wound") and (verdict.get("harm") or {}).get("result") in ("wounded", "disabled", "killed"):
        problems.append(f"wounded: {(verdict.get('harm') or {}).get('result')}")
    if case.get("require_action") and verdict["category"] == "success" and verdict["action"] != case["require_action"]:
        problems.append(f"action {verdict['action']} is not {case['require_action']}")
    recorded = {claim["id"] for claim in verdict.get("property", [])}
    for item in case.get("require_property_if_success", []):
        if verdict["category"] == "success" and item not in recorded:
            problems.append(f"use of {item} was not recorded as someone else's property")
    harm = verdict.get("harm") or {}
    if harm.get("result") in case.get("forbid_harm_results", []):
        problems.append(f"harm result {harm['result']} is not plausible here")
    wanted_steps = case.get("require_step_actions")
    if wanted_steps and [st["action"] for st in verdict.get("steps", [])] != wanted_steps:
        problems.append(f"steps {[st['action'] for st in verdict.get('steps', [])]} are not {wanted_steps}")
    if case.get("require_crafted_weapon") and verdict["category"] == "success":
        if not harm or not str(harm.get("weapon_id", "")).startswith("made_"):
            problems.append(f"the attack did not use the object made earlier (weapon {harm.get('weapon_id')})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}': add OPENAI_API_KEY to backend/.env first.")
        return 1
    cases = json.loads((ROOT / "evals" / "craft_cases.json").read_text(encoding="utf-8"))["cases"]
    cases = [c for c in cases if not args.case or c["id"] in args.case]
    report, latencies, tokens_in, tokens_out = [], [], 0, 0
    for case in cases:
        passes = 0
        for run in range(args.runs):
            state = world_with(case)
            context = crafting.build_context(state, case["text"], [])
            judged = judge.judge_craft(context)
            _, verdict, _ = crafting.resolve_attempt(copy.deepcopy(state), "eval0000", case["text"], judged.result,
                                                     judged.error if judged.status != "ok" else None, "eval", 0)
            problems = check(case, judged, verdict)
            passes += not problems
            latencies.append(judged.latency_ms)
            tokens_in += judged.input_tokens
            tokens_out += judged.output_tokens
            report.append({"case": case["id"], "group": case["group"], "run": run, "pass": not problems,
                           "problems": problems, "category": verdict["category"], "reason": verdict["reason"],
                           "validator_notes": verdict["notes"], "judge": judged.as_dict()})
            mark = "PASS" if not problems else "FAIL " + "; ".join(problems)
            print(f"  {case['id']:<20} run {run + 1}: {verdict['category']:<20} {judged.latency_ms:>6} ms  {mark}")
        print(f"{case['id']:<22} {passes}/{args.runs}")
    total = sum(r["pass"] for r in report)
    price_in, price_out = PRICES_PER_MTOK.get(config.judge_model(), (0.0, 0.0))
    cost = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0
    summary = {"model": config.judge_model(), "reasoning": config.judge_reasoning(),
               "prompt_version": judge.PROMPT_VERSION, "passed": total, "total": len(report),
               "latency_p50_ms": statistics.median(latencies) if latencies else 0, "latency_p95_ms": p95,
               "input_tokens": tokens_in, "output_tokens": tokens_out, "estimated_cost_usd": round(cost, 4)}
    print(json.dumps(summary, indent=1))
    out = ROOT / "evals" / "results" / f"craft_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": report}, indent=1), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 0 if total == len(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
