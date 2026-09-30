"""Live check of the tutorial's suggested words (D-52): the exact sentences the guide offers ("Type it for me") must
work with the real judge, in the world as the tutorial leaves it at that step.

    backend/.venv/Scripts/python.exe evals/run_tutorial_live.py [--runs 3] [--demo "other words to try"]

The chain: make the poultice (step "remedy"), put it on Jory's burn ("treat"), then show someone something
("wonder"), each judged and applied as a real attempt beside Jory. Costs about a cent per run.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import crafting  # noqa: E402
import gear  # noqa: E402
import minds  # noqa: E402
import tutorial  # noqa: E402
from ai import config, judge  # noqa: E402


def suggestion(step_id: str) -> str:
    step = next(s for s in tutorial.STEPS if s["id"] == step_id)
    return step["suggest"]["text"]


def world() -> dict:
    state = app.initial_state({"id": "tutlive", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION, "scenario": "tutorial"})
    state.setdefault("pending_minds", [])
    jory = minds.find(state["npcs"], "npc_jory_venn")
    gear.add_condition(jory, {"kind": "burn", "area": "arm", "severity": 18}, 0)
    for oid in ("plantain_a", "flint_a", "grass_a"):  # What the guide has the player pick up by then.
        state["objects"][oid]["holder_id"] = "player"
    state["player"].update(x=jory["x"], y=jory["y"] + 1)
    return state


def attempt(state: dict, text: str) -> dict:
    context = crafting.build_context(state, text, [])
    judged = judge.judge_craft(context)
    payload, verdict, _ = crafting.resolve_attempt(copy.deepcopy(state), "tutlive0", text, judged.result,
                                                   judged.error if judged.status != "ok" else None, "tut", 0)
    if verdict["category"] == "success":
        crafting.apply_payload(state, payload)
        minds.apply_perceptions(state, minds.perceive(state, payload["journal_entry"]))
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--demo", default=None, help="try these words for the demonstration instead")
    args = parser.parse_args()
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}': add OPENAI_API_KEY to backend/.env first.")
        return 1
    demo_text = args.demo or suggestion("wonder")
    steps = [("remedy", suggestion("remedy"), {"kind": "carrying_remedy", "treats": "burn"}),
             ("treat", suggestion("treat"), {"kind": "condition_treated", "npc": "npc_jory_venn", "condition": "burn"}),
             ("wonder", demo_text, {"kind": "demonstration_seen"})]
    report, failures = [], 0
    for run in range(args.runs):
        state = world()
        for step_id, text, check in steps:
            if step_id == "wonder":
                state["objects"]["nail_a"]["holder_id"] = "player"
            verdict = attempt(state, text)
            ok = tutorial.holds(state, check)
            failures += not ok
            report.append({"run": run + 1, "step": step_id, "text": text, "ok": ok, "category": verdict["category"],
                           "reason": verdict["reason"]})
            print(f"{'PASS' if ok else 'FAIL'}  run {run + 1}  {step_id:7} “{text}” → {verdict['category']}: "
                  f"{verdict['reason'][:160]}")
    out = ROOT / "evals" / "results" / f"tutorial_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(report) - failures}/{len(report)} passed. Report: {out.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
