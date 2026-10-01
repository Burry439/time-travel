"""Live check of the tutorial's suggested words (D-52): the exact sentences the guide offers ("Type it for me") must
work with the real judge, in the world as the tutorial leaves it at that step.

    backend/.venv/Scripts/python.exe evals/run_tutorial_live.py [--runs 3] [--demo "other words to try"]

The chain: make the poultice (step "remedy"), put it on Jory's burn ("treat"), then make a fire where Kade can
see it ("fire", D-57: flint, the broken steel file and dry grass), each judged and applied as a real attempt. The fire
is also tried in the words players really type (FIRE_WORDS). Costs about two cents per run.
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
import cast  # noqa: E402
import consequences  # noqa: E402
import gear  # noqa: E402
import judge_view  # noqa: E402
import perception  # noqa: E402
import rules  # noqa: E402
import scenario  # noqa: E402
from ai import config, judge  # noqa: E402

FIRE_WORDS = ["I strike the steel file with the flint over the dried grass",
              "make a fire with the flint, the steel file and the dry grass"]


def suggestion(step_id: str) -> str:
    step = next(s for s in scenario.STEPS if s["id"] == step_id)
    return step["suggest"]["text"]


def world() -> dict:
    state = app.initial_state({"id": "tutlive", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION, "scenario": "tutorial"})
    state.setdefault("pending_minds", [])
    jory = cast.find(state["npcs"], "npc_jory_venn")
    gear.add_condition(jory, {"kind": "burn", "area": "arm", "severity": 18}, 0)
    for oid in ("plantain_a", "flint_a", "grass_a"):  # What the guide has the player pick up by then.
        state["objects"][oid]["holder_id"] = "player"
    state["player"].update(x=jory["x"], y=jory["y"] + 1)
    return state


def attempt(state: dict, text: str) -> dict:
    context = judge_view.build_context(state, text, [])
    judged = judge.judge_craft(context)
    payload, verdict, _ = consequences.resolve_attempt(copy.deepcopy(state), "tutlive0", text, judged.result,
                                                   judged.error if judged.status != "ok" else None, "tut", 0)
    if verdict["category"] == "success":
        consequences.apply_payload(state, payload)
        perception.apply_perceptions(state, perception.perceive(state, payload["journal_entry"]))
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--demo", default=None, help="try these words for the demonstration instead")
    args = parser.parse_args()
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}': add OPENAI_API_KEY to backend/.env first.")
        return 1
    fire_check = {"kind": "made_seen", "flag": "heat_source", "by": "npc_kade_east"}
    steps = [("remedy", suggestion("remedy"), {"kind": "carrying_remedy", "treats": "burn"}),
             ("treat", suggestion("treat"), {"kind": "condition_treated", "npc": "npc_jory_venn", "condition": "burn"}),
             ("fire", args.demo or suggestion("fire"), fire_check)]
    report, failures = [], 0
    for run in range(args.runs):
        state = world()
        chain = steps + [("fire", words, fire_check) for words in ([] if args.demo else FIRE_WORDS)]
        for step_id, text, check in chain:
            if step_id == "fire":  # By now: the steel file in hand, and Kade beside the stranger (D-57).
                if any(o.get("created_by") == "player" and "heat_source" in o.get("flags", [])
                       for o in state["objects"].values()):
                    state = world()  # Each wording tried on its own, from before any fire.
                state["objects"]["steel_file"]["holder_id"] = "player"
                kade = cast.find(state["npcs"], "npc_kade_east")
                kade.update(x=state["player"]["x"] + 2, y=state["player"]["y"])
            verdict = attempt(state, text)
            ok = rules.holds(state, check, {"progress": state.get("tutorial") or {}})
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
