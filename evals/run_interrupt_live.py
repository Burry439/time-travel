"""Live evaluation of who speaks up in a conversation they weren't addressed in (D-71): the real voice (and, when
on, the bystander check) through the game's code.

    backend/.venv/Scripts/python.exe evals/run_interrupt_live.py [--runs 3] [--case hessa_small_talk ...]
    BYSTANDER_GATE=off backend/.venv/Scripts/python.exe evals/run_interrupt_live.py   # today's behaviour

Each case talks to one person with others in earshot, and says what each of them should do:
- "quiet": they shouldn't cut in (any line from them is an interruption);
- "speak": it's their business, so they should say something at least once;
- "react": they should at least take it in (speak, or decide something silently: an intent or a move).
Needs OPENAI_API_KEY in backend/.env; a few cents a run. Writes evals/results/interrupt_*.json.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import app  # noqa: E402
import encounter  # noqa: E402
import rounds  # noqa: E402
from run_talk_evals import world_for  # noqa: E402

LUNA_PER_MTOK = (0.1, 0.5)  # input, output USD
QUIET_MOVES = ("", "answer")  # A silent decision that changes nothing.

CASES = [
    {
        "id": "hessa_small_talk",
        "npc": "npc_hessa_marr",
        "nearby": [{"npc": "npc_mara_venn", "dx": 2}, {"npc": "npc_tomas_reed", "dx": -2}],
        "lines": ["Good morning! Fine weather today.", "Is the inn busy this time of year?",
                  "What's good to eat around here?"],
        "expect": {"npc_mara_venn": "quiet", "npc_tomas_reed": "quiet"},
    },
    {
        "id": "guard_directions",
        "npc": "npc_oren_dast",
        "nearby": [{"npc": "npc_kade_east", "dx": 2}, {"npc": "npc_jory_venn", "dx": -2}],
        "lines": ["Which way is the well?", "Thanks. Is the water good to drink?"],
        "expect": {"npc_kade_east": "quiet", "npc_jory_venn": "quiet"},
    },
    {
        "id": "darin_haggle",
        "npc": "npc_darin_ko",
        "nearby": [{"npc": "npc_elin_west", "dx": 2}, {"npc": "npc_jory_venn", "dx": -2}],
        "lines": ["What are you selling today?", "How much for a length of good rope?"],
        "expect": {"npc_elin_west": "quiet", "npc_jory_venn": "quiet"},
    },
    {
        "id": "mara_craft",
        "npc": "npc_mara_venn",
        "nearby": [{"npc": "npc_hessa_marr", "dx": 2}, {"npc": "npc_elin_west", "dx": -2}],
        "lines": ["How long have you worked a forge?", "What's the hardest thing you've ever made?"],
        "expect": {"npc_hessa_marr": "quiet", "npc_elin_west": "quiet"},
    },
    {
        "id": "about_her_brother",
        "npc": "npc_hessa_marr",
        "nearby": [{"npc": "npc_bren_marr", "dx": 2}, {"npc": "npc_tomas_reed", "dx": -2}],
        "lines": ["That guard there, Bren: I hear he drinks on duty and lets anyone through for a coin."],
        "expect": {"npc_bren_marr": "speak", "npc_tomas_reed": "quiet"},
    },
    {
        "id": "accused_in_earshot",
        "npc": "npc_hessa_marr",
        "nearby": [{"npc": "npc_jory_venn", "dx": 2}, {"npc": "npc_elin_west", "dx": -2}],
        "lines": ["I think that lad there, Jory, stole my purse while I slept by the road."],
        "expect": {"npc_jory_venn": "speak"},
    },
    {
        "id": "question_to_all",
        "npc": "npc_oren_dast",
        "nearby": [{"npc": "npc_bren_marr", "dx": 2}, {"npc": "npc_kade_east", "dx": -2}],
        "lines": ["Can any of you guards tell me who decides who gets through this gate?"],
        "expect_any": {"speak": ["npc_bren_marr", "npc_kade_east"]},
        "expect": {},
    },
    {
        "id": "confession_overheard",
        "npc": "npc_hessa_marr",
        "nearby": [{"npc": "npc_kade_east", "dx": 2}],
        "lines": ["Between you and me, I took a purse off a sleeping traveller on the road this morning."],
        "expect": {"npc_kade_east": "react"},
    },
]


def scene_round(state: dict, npc_id: str, text: str) -> dict:
    """One round of words, as /act plays it, recording who spoke and who decided silently before code applies it."""
    request = rounds.EncounterAct(kind="say", text=text, target_id=npc_id, expected_version=state["event_seq"],
                                  request_id=f"eval-{state['event_seq']}")
    draft, record = rounds._round_draft(state, "interrupteval", request, [], None)
    happened = " ".join(record["happened"]) or None
    moment = rounds.scene(draft, record["replier"], text, happened, True)
    call = moment["call"]
    if call.status != "ok":
        return {"said": text, "error": call.error, "ms": call.latency_ms}
    spoke = [{"who": line["speaker_id"], "text": line["text"]} for line in call.lines if line["speaker_id"] != npc_id]
    silent = [
        {"who": line["speaker_id"], "move": line.get("move", ""), "intents": [i.get("kind") for i in line.get("intents", [])]}
        for line in call.decisions
    ]
    now = draft["sim_time_ms"]
    said = rounds.apply_scene(draft, moment, text, happened, now)
    encounter.finish(draft, record, now, [{k: v for k, v in s.items() if k != "trace"} for s in said])
    draft["event_seq"] += 1
    draft["sim_time_ms"] = now + encounter.round_ms(record)
    state.clear()
    state.update(draft)
    return {
        "said": text,
        "spoke": spoke,
        "silent": silent,
        "turns": getattr(call, "turns", []),
        "checks": getattr(call, "checks", []),
        "ms": call.latency_ms,
        "usd": (call.input_tokens * LUNA_PER_MTOK[0] + call.output_tokens * LUNA_PER_MTOK[1]) / 1e6,
    }


def score(case: dict, turns: list[dict]) -> dict:
    """Per bystander: interruptions (quiet), whether they spoke when they should (speak), whether they took it in."""
    out = {"unwanted": 0, "quiet_rounds": 0, "wanted": 0, "wanted_of": 0, "reacted": 0, "reacted_of": 0, "notes": []}
    rounds_ok = [t for t in turns if "error" not in t]
    for who, expected in case["expect"].items():
        spoke = [t for t in rounds_ok if any(s["who"] == who for s in t["spoke"])]
        moved = [
            t for t in rounds_ok
            if any(s["who"] == who and (s["move"] not in QUIET_MOVES or s["intents"]) for s in t["silent"])
        ]
        if expected == "quiet":
            out["quiet_rounds"] += len(rounds_ok)
            out["unwanted"] += len(spoke)
            out["notes"] += [f"{who.split('_')[1]} cut in: {s['text']}" for t in spoke for s in t["spoke"]
                             if s["who"] == who]
        elif expected == "speak":
            out["wanted_of"] += 1
            out["wanted"] += bool(spoke)
            if not spoke:
                out["notes"].append(f"{who.split('_')[1]} kept quiet")
        else:
            out["reacted_of"] += 1
            out["reacted"] += bool(spoke or moved)
            if not (spoke or moved):
                out["notes"].append(f"{who.split('_')[1]} took no notice")
    group = (case.get("expect_any") or {}).get("speak", [])
    if group:  # Somebody among them should answer a question put to all of them.
        out["wanted_of"] += 1
        hit = any(s["who"] in group for t in rounds_ok for s in t["spoke"])
        out["wanted"] += hit
        if not hit:
            out["notes"].append(f"none of {[g.split('_')[1] for g in group]} answered")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case", nargs="*")
    args = parser.parse_args(argv)
    if app.ai_config.mode() != "live":
        print(f"AI mode is '{app.ai_config.mode()}': add OPENAI_API_KEY to backend/.env.")
        return 1
    gate = os.environ.get("BYSTANDER_GATE", "on")
    cases = [c for c in CASES if not args.case or c["id"] in args.case]
    report = []
    for case in cases:
        for run in range(args.runs):
            state, _ = world_for({"npc": case["npc"], "nearby": case["nearby"]})
            turns = [scene_round(state, case["npc"], line) for line in case["lines"]]
            result = score(case, turns)
            report.append({"case": case["id"], "run": run + 1, **result, "turns": turns})
            errors = [t["error"] for t in turns if "error" in t]
            print(f"{case['id']:22} run {run + 1}: unwanted {result['unwanted']}/{result['quiet_rounds']}  "
                  f"wanted {result['wanted']}/{result['wanted_of']}  reacted {result['reacted']}/{result['reacted_of']}"
                  + (f"  errors {errors}" if errors else ""))
            for note in result["notes"]:
                print(f"      - {note[:200]}")
    rounds_all = [t for r in report for t in r["turns"] if "error" not in t]
    total = lambda key: sum(r[key] for r in report)  # noqa: E731
    times = sorted(t["ms"] for t in rounds_all)
    summary = {
        "gate": gate,
        "unwanted": f"{total('unwanted')}/{total('quiet_rounds')}",
        "wanted": f"{total('wanted')}/{total('wanted_of')}",
        "reacted": f"{total('reacted')}/{total('reacted_of')}",
        "round_ms_p50": statistics.median(times) if times else None,
        "round_ms_p95": times[int(0.95 * (len(times) - 1))] if times else None,
        "usd_per_round": statistics.mean(t["usd"] for t in rounds_all) if rounds_all else None,
    }
    print(f"\nBYSTANDER_GATE={gate}: interruptions {summary['unwanted']} quiet rounds · spoke when it was their "
          f"business {summary['wanted']} · took it in {summary['reacted']} · round p50 {summary['round_ms_p50']} ms, "
          f"p95 {summary['round_ms_p95']} ms · ${summary['usd_per_round'] or 0:.5f} a round (voice only)")
    out = ROOT / "evals" / "results" / f"interrupt_{gate}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "report": report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
