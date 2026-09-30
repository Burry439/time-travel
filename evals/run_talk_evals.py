"""Live evaluation of conversations: the real voice model (Luna) through the game's code, one scene per round (D-48).

    backend/.venv/Scripts/python.exe evals/run_talk_evals.py [--runs 2] [--case injection_admit ...]

Needs OPENAI_API_KEY in backend/.env. Costs a little real money
(about a tenth of a cent per round). Writes a JSON report to evals/results/ and prints a summary.
A case's lines are what the stranger says, or {"say": ..., "happened": ...} for something the stranger did
as they said it (e.g. a demonstration); "nearby" places other people a step or two away, free to join in.
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
import combat  # noqa: E402
import encounter  # noqa: E402
import minds  # noqa: E402
import rounds  # noqa: E402
import talk  # noqa: E402

LUNA_PER_MTOK = (0.1, 0.5)  # input, output USD
# Words that promise a later errand (D-51): the line's move must carry it out.
PROMISE = re.compile(r"\b(i'?ll|i will|i'm going to|i shall)\s+(go|run|head|walk|tell|ask|speak|talk|have a word|"
                     r"fetch|bring|send|find|put in a word|mention|let \w+ know|pass)\b", re.IGNORECASE)


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
    for near in case.get("nearby", []):  # Others a step or two away, free to listen and join in.
        other = minds.find(state["npcs"], near["npc"])
        other.update(x=state["player"]["x"] + near.get("dx", 2), y=state["player"]["y"] + near.get("dy", 0))
        minds.mind(other)["job"] = None
    if case.get("reason"):  # They came up to the stranger for a reason (a halt, a confrontation).
        encounter.join(state, person, case["reason"], None, 0)
    for condition in case.get("hurt", []):  # e.g. Jory's burn
        import gear
        gear.add_condition(person, condition, 0)
    for object_id, fields in case.get("objects", {}).items():  # e.g. a poultice, in someone's hands
        state["objects"][object_id].update(fields)
    if case.get("fight"):  # These people are attacking the stranger right now (D-51: talk still reaches them).
        combat.start(state, case["fight"], 0, "developer", lethal=False)
    return state, person


def exchange(state: dict, npc_id: str, line) -> dict:
    """One round exactly as /act plays it for words, minus the database and the world moving on."""
    text, extra = (line, None) if isinstance(line, str) else (line.get("say", ""), line.get("happened"))
    request = rounds.EncounterAct(kind="say", text=text, target_id=npc_id, expected_version=state["event_seq"],
                                  request_id=f"eval-{state['event_seq']}")
    draft, record = rounds._round_draft(state, "talkeval", request, [], None)
    happened = " ".join([*record["happened"], *([extra] if extra else [])]) or None
    moment = rounds.scene(draft, record["replier"], text, happened, True)
    call = moment["call"]
    if call.status != "ok":
        return {"said": text, "error": call.error, "voice_ms": call.latency_ms}
    before = dict(talk.regard(minds.find(draft["npcs"], npc_id)))
    now = draft["sim_time_ms"]
    said = rounds.apply_scene(draft, moment, text, happened, now)
    encounter.finish(draft, record, now, [{k: v for k, v in s.items() if k != "trace"} for s in said])
    draft["event_seq"] += 1
    draft["sim_time_ms"] = now + encounter.round_ms(record)
    state.clear()
    state.update(draft)
    after = talk.regard(minds.find(state["npcs"], npc_id))
    mine = next((s for s in said if s["npc_id"] == npc_id), None)
    return {"said": text, "reply": mine["key"] if mine else None,
            "lines": [{"who": s["npc_id"], "key": s["key"], "line": s["line"], "joined": s["trace"]["joined"]}
                      for s in said],
            "keys": [s["key"] for s in said], "line": " ".join(s["line"] for s in said),
            "hostile": encounter.hostile(state),
            "trust": round(after["trust"] - before["trust"], 3),
            "suspicion": round(after["suspicion"] - before["suspicion"], 3),
            "voice_ms": call.latency_ms,
            "voice_usd": (call.input_tokens * LUNA_PER_MTOK[0] + call.output_tokens * LUNA_PER_MTOK[1]) / 1e6}


def check(case: dict, turns: list[dict], start: dict, end: dict) -> list[str]:
    problems = [f"voice failed: {t['error']}" for t in turns if "error" in t]
    keys = [k for t in turns for k in t.get("keys", [])]  # Anyone's move: a guard beside them admitting counts too.
    for prefix in case.get("forbid", []):
        if any(k.startswith(prefix) for k in keys):
            problems.append(f"chose forbidden {prefix}")
    if case.get("expect_any") and not any(k.startswith(p) for k in keys for p in case["expect_any"]):
        problems.append(f"never chose any of {case['expect_any']} (chose {keys})")
    if "max_trust_gain" in case and end["trust"] - start["trust"] > case["max_trust_gain"] + 1e-9:
        problems.append(f"trust rose {end['trust'] - start['trust']:.2f}")
    if case.get("trust_falls") and not end["trust"] < start["trust"]:
        problems.append("trust did not fall")
    if "max_suspicion_gain" in case and end["suspicion"] - start["suspicion"] > case["max_suspicion_gain"] + 1e-9:
        problems.append(f"suspicion rose {end['suspicion'] - start['suspicion']:.2f}")
    if case.get("suspicion_rises") and not end["suspicion"] > start["suspicion"]:
        problems.append("suspicion did not rise")
    if case.get("line_needs_any") and not any(w in t.get("line", "").lower() for t in turns
                                              for w in case["line_needs_any"]):
        problems.append(f"said none of {case['line_needs_any']}")
    for word in case.get("line_must_not_contain", []):
        for t in turns:
            if word.lower() in f" {t.get('line', '').lower()} ":
                problems.append(f"said '{word.strip()}': {t['line']}")
    for t in turns:  # Always: a promise to go and do something is a move that does it (D-51).
        for line in t.get("lines", []):
            if PROMISE.search(line["line"]) and line["key"].split(":")[0] not in talk.ERRANDS:
                problems.append(f"promised without doing it ({line['key']}): {line['line']}")
    speakers = {line["who"] for t in turns for line in t.get("lines", [])}
    if case.get("expect_speakers_any") and not speakers & set(case["expect_speakers_any"]):
        problems.append(f"none of {case['expect_speakers_any']} spoke (only {sorted(speakers)})")
    if case.get("stays_friendly") and any(t.get("hostile") for t in turns):
        problems.append("the conversation turned hostile")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--case", nargs="*")
    args = parser.parse_args(argv)
    if app.ai_config.mode() != "live":
        print(f"AI mode is '{app.ai_config.mode()}': add OPENAI_API_KEY to backend/.env.")
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
            print(f"{'PASS' if not problems else 'FAIL'}  {case['id']:28} " + " | ".join(
                " / ".join(f"{l['who'].split('_')[1]} {l['key']}: {l['line']}" for l in t.get("lines", []))
                or str(t.get("error")) for t in turns)[:600])
            for problem in problems:
                print(f"      - {problem}")
    exchanges = [t for r in report for t in r["turns"] if "lines" in t]
    if exchanges:
        print(f"\n{len(report) - failures}/{len(report)} passed · {len(exchanges)} rounds · voice median "
              f"{statistics.median(t['voice_ms'] for t in exchanges):.0f} ms · p95 "
              f"{sorted(t['voice_ms'] for t in exchanges)[int(0.95 * (len(exchanges) - 1))]:.0f} ms · mean cost "
              f"${statistics.mean(t['voice_usd'] for t in exchanges):.5f} per round · "
              f"{statistics.mean(len(t['lines']) for t in exchanges):.1f} lines per round")
    out = ROOT / "evals" / "results" / f"talk_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
