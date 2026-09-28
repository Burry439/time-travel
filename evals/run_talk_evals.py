"""Live evaluation of conversations: the real decider (Jev) and voice (Luna) through the game's code.

    backend/.venv/Scripts/python.exe evals/run_talk_evals.py [--runs 2] [--case injection_admit ...]

Needs TYPESAFE_API_KEY (Jev) and OPENAI_API_KEY (voice) in backend/.env. Costs a little real money
(about a tenth of a cent per exchange). Writes a JSON report to evals/results/ and prints a summary.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import minds  # noqa: E402
import rounds  # noqa: E402
import talk  # noqa: E402
from ai import decider, voice  # noqa: E402

LUNA_PER_MTOK = (0.1, 0.5)  # input, output USD


def world_for(case: dict) -> tuple[dict, dict]:
    state = app.initial_state({"id": "talkeval", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION})
    state.setdefault("pending_minds", [])
    person = minds.find(state["npcs"], case["npc"])
    state["player"].update(x=person["x"], y=person["y"] + 1)
    for index, memory in enumerate(case.get("memories", [])):
        minds.remember(person, {"victim": None, "item": None, "event": 900 + index, "at": 0, **memory})
    minds.mind(person)["talk"] = [dict(t, at=0) for t in case.get("talk", [])]
    talk.regard(person).update(case.get("regard", {}))  # e.g. awe or trust already earned
    for object_id in case.get("carry", []):  # e.g. the stolen rope, in the stranger's hands
        state["objects"][object_id]["holder_id"] = "player"
    if case.get("reason"):  # They came up to the stranger for a reason (a halt, a confrontation).
        state["encounter"] = {"id": "enc_eval", "participants": [person["id"]], "opened_by": person["id"],
                              "reason": case["reason"], "round": 1, "intents": {}, "log": [], "started_at": 0}
    return state, person


def exchange(state: dict, npc_id: str, text: str) -> dict:
    """One exchange exactly as /say does it, minus the database."""
    person = minds.find(state["npcs"], npc_id)
    out = rounds._speak(state, person, text, None, talk.request(state, person, text), "talkeval", True)  # D-44
    decided, spoken, key = out["decided"], out["spoken"], out["key"]
    if not decided.ok and spoken.status != "ok":
        return {"error": decided.error or spoken.error, "jev_ms": decided.latency_ms}
    before = dict(talk.regard(person))
    talk.exchange(state, npc_id, text, out["answers"], key, spoken.text, [], note=spoken.remember,
                  name_given=spoken.stranger_name)
    state["event_seq"] += 1
    after = talk.regard(minds.find(state["npcs"], npc_id))
    return {"said": text, "reply": key, "line": spoken.text, "voice": spoken.status, "voice_error": spoken.error,
            "trust": round(after["trust"] - before["trust"], 3),
            "suspicion": round(after["suspicion"] - before["suspicion"], 3),
            "jev_ms": decided.latency_ms, "jev_usd": decided.cost_usd or 0.0, "provider": decided.provider,
            "voice_ms": spoken.latency_ms,
            "voice_usd": (spoken.input_tokens * LUNA_PER_MTOK[0] + spoken.output_tokens * LUNA_PER_MTOK[1]) / 1e6}


def check(case: dict, turns: list[dict], start: dict, end: dict) -> list[str]:
    problems = [f"decider failed: {t['error']}" for t in turns if "error" in t]
    keys = [t["reply"] for t in turns if "reply" in t]
    for prefix in case.get("forbid", []):
        if any(k.startswith(prefix) for k in keys):
            problems.append(f"chose forbidden {prefix}")
    if case.get("expect_any") and not any(k.startswith(p) for k in keys for p in case["expect_any"]):
        problems.append(f"never chose any of {case['expect_any']} (chose {keys})")
    if "max_trust_gain" in case and end["trust"] - start["trust"] > case["max_trust_gain"] + 1e-9:
        problems.append(f"trust rose {end['trust'] - start['trust']:.2f}")
    if case.get("trust_falls") and not end["trust"] < start["trust"]:
        problems.append("trust did not fall")
    if case.get("suspicion_rises") and not end["suspicion"] > start["suspicion"]:
        problems.append("suspicion did not rise")
    if case.get("line_needs_any") and not any(w in t.get("line", "").lower() for t in turns
                                              for w in case["line_needs_any"]):
        problems.append(f"said none of {case['line_needs_any']}")
    for word in case.get("line_must_not_contain", []):
        for t in turns:
            if word.lower() in f" {t.get('line', '').lower()} ":
                problems.append(f"said '{word.strip()}': {t['line']}")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--case", nargs="*")
    args = parser.parse_args(argv)
    if decider.mode() != "jev" or app.ai_config.mode() != "live":
        print(f"Decider is '{decider.mode()}' and AI mode '{app.ai_config.mode()}': add both keys to backend/.env.")
        return 1
    cases = [c for c in json.loads((ROOT / "evals" / "talk_cases.json").read_text(encoding="utf-8"))["cases"]
             if not args.case or c["id"] in args.case]
    report, failures = [], 0
    for case in cases:
        for run in range(args.runs):
            state, person = world_for(case)
            start = dict(talk.regard(person))
            turns = [exchange(state, case["npc"], line) for line in case["lines"]]
            end = talk.regard(minds.find(state["npcs"], case["npc"]))
            problems = check(case, turns, start, end)
            if case.get("hint_any"):
                hinted = any(w in t.get("line", "").lower() for t in turns for w in case["hint_any"])
                print(f"      (soft) hints at what would change their mind: {'yes' if hinted else 'no'}")
            failures += bool(problems)
            report.append({"case": case["id"], "run": run + 1, "ok": not problems, "problems": problems,
                           "turns": turns})
            print(f"{'PASS' if not problems else 'FAIL'}  {case['id']:28} " +
                  " | ".join(f"{t.get('reply')}: {t.get('line', t.get('error'))}" for t in turns)[:400])
            for problem in problems:
                print(f"      - {problem}")
    exchanges = [t for r in report for t in r["turns"] if "reply" in t]
    if exchanges:
        total = [t["jev_ms"] + t["voice_ms"] for t in exchanges]
        print(f"\n{len(report) - failures}/{len(report)} passed · {len(exchanges)} exchanges · "
              f"Jev median {statistics.median(t['jev_ms'] for t in exchanges):.0f} ms · voice median "
              f"{statistics.median(t['voice_ms'] for t in exchanges):.0f} ms · p95 total "
              f"{sorted(total)[int(0.95 * (len(total) - 1))]:.0f} ms · mean cost "
              f"${statistics.mean(t['jev_usd'] + t['voice_usd'] for t in exchanges):.5f} per exchange · "
              f"voice fallbacks {sum(t['voice'] != 'ok' for t in exchanges)}")
    out = ROOT / "evals" / "results" / f"talk_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
