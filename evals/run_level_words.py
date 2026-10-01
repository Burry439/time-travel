"""Live check of a training level's words (D-59): every "do" in its steps' playtests, and the other wordings in
try_also, must work with the real judge in the world as the level leaves it at that step, and complete the step.

    backend/.venv/Scripts/python.exe evals/run_level_words.py --level cup_of_water [--runs 2]

The level is played from its start in the backend alone: walking is a step to the target, taking is taking, and
each "do" is judged and applied as a real attempt, then the step's own check decides. Talk, the interface and the
device are skipped (their checks are their own evals). Writes evals/results/words_<level>_*.json. A few cents a run.
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
import content  # noqa: E402
import judge_view  # noqa: E402
import perception  # noqa: E402
import rules  # noqa: E402
import scenario  # noqa: E402
from ai import config, judge  # noqa: E402

FAILS = ("failed", "blocked")  # A failure the world explains, which a step may ask for (attempt_failed).


def start(level_id: str) -> dict:
    state = app.initial_state({"id": "words", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION, "scenario": level_id})
    state.setdefault("pending_minds", [])
    return state


def where(state: dict, target) -> tuple[int, int]:
    if isinstance(target, list):
        return target[0], target[1]
    person = cast.find(state["npcs"], target)
    thing = state["objects"].get(target)
    x, y = (person["x"], person["y"]) if person else (thing["x"], thing["y"])
    return x, y


def walk_to(state: dict, target) -> None:
    """Stand on the nearest open cell beside it."""
    import paths

    x, y = where(state, target)
    grid = paths.grid(state)
    near = min((c for c in ((x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)) if grid.walkable(c)),
               key=lambda c: (abs(c[0] - x) + abs(c[1] - y), c))
    state["player"].update(x=near[0], y=near[1])


def attempt(state: dict, text: str) -> dict:
    judged = judge.judge_craft(judge_view.build_context(state, text, []))
    payload, verdict, _ = consequences.resolve_attempt(copy.deepcopy(state), "words000", text, judged.result,
                                                   judged.error if judged.status != "ok" else None, "words", 0)
    if verdict["category"] == "success" or verdict["category"] in FAILS:
        state["event_seq"] += 1
        consequences.apply_payload(state, payload)
        perception.apply_perceptions(state, perception.perceive(state, payload["journal_entry"]))
    return verdict


def play(state: dict, step: dict, words: str | None) -> list[dict]:
    """The step's playtest, with its do in these words; what each do did."""
    done = []
    for action in step.get("playtest", []):
        if "walk_to" in action:
            walk_to(state, action["walk_to"])
        elif "take" in action:
            state["objects"][action["take"]]["holder_id"] = "player"
        elif "do" in action:
            done.append({"text": words or action["do"], **attempt(state, words or action["do"])})
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", required=True)
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}': add OPENAI_API_KEY to backend/.env first.")
        return 1
    steps = content.LEVELS[args.level]["steps"]
    report, failures = [], 0
    for run in range(args.runs):
        state = start(args.level)
        for index, step in enumerate(steps):
            state["tutorial"].update(step=index, read=index, started_seq=state["event_seq"])
            does = [a for a in step.get("playtest", []) if "do" in a]
            for words in (step.get("try_also", []) + [None]) if does else [None]:  # Others first, on copies.
                trial = copy.deepcopy(state) if words else state  # Other wordings are tried on a copy.
                tried = play(trial, step, words)
                if not tried:
                    continue
                ok = rules.holds(trial, step["check"], {"progress": trial["tutorial"]})
                failures += not ok
                for verdict in tried:
                    report.append({"run": run + 1, "step": step["id"], "text": verdict["text"], "ok": ok,
                                   "category": verdict["category"], "reason": verdict["reason"]})
                    print(f"{'PASS' if ok else 'FAIL'}  run {run + 1}  {step['id']:7} “{verdict['text']}” → "
                          f"{verdict['category']}: {verdict['reason'][:150]}")
            if not does:  # Walking, talking, the interface: as if it happened (their checks aren't this eval's).
                play(state, step, None)
            scenario.run(state, step.get("on_done", []), state.get("sim_time_ms", 0))
    out = ROOT / "evals" / "results" / f"words_{args.level}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(report) - failures}/{len(report)} passed. Report: {out.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # The reports quote words; a Windows console would refuse them.
    raise SystemExit(main())
