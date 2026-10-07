"""Live comparison of the two ways the decider can sort a typed line (D-71): OpenAI's Decisions API against a Responses
call with a strict schema, on the same real lines, through intent.classify as the game calls it.

    backend/.venv/Scripts/python.exe evals/run_intent_evals.py [--backend decisions responses] [--runs 3]

Cases are evals/intent_cases.json (lines mostly from the game's own journeys). Lines code sorts alone are skipped.
Needs OPENAI_API_KEY in backend/.env; well under a cent a line. Writes evals/results/intent_*.json.
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

import intent  # noqa: E402
from ai import config  # noqa: E402

PER_MTOK = {"decisions": (0.10, 0.0), "llm": (0.10, 0.50)}  # input, output USD per million tokens


def run(backend: str, cases: list[dict], runs: int) -> dict:
    os.environ["DECIDER_BACKEND"] = backend
    rows = []
    for case in cases:
        for _ in range(runs):
            kind, how, call = intent.classify(case["text"], case["near"], case["talking"] or None)
            provider = call.provider if call else "none"
            price = PER_MTOK.get(provider, PER_MTOK["llm"])
            rows.append({
                "text": case["text"], "expect": case["expect"], "got": kind, "how": how,
                "ok": kind in case["expect"], "ms": call.latency_ms if call else 0,
                "provider": provider, "fallback_from": call.fallback_from if call else None,
                "usd": ((call.input_tokens * price[0] + call.output_tokens * price[1]) / 1e6) if call else 0.0,
            })
    times = sorted(r["ms"] for r in rows)
    by_kind: dict[str, list[bool]] = {}
    for r in rows:
        by_kind.setdefault(r["expect"][0], []).append(r["ok"])
    return {
        "backend": backend,
        "accuracy": sum(r["ok"] for r in rows) / len(rows),
        "right": sum(r["ok"] for r in rows),
        "of": len(rows),
        "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_kind.items())},
        "p50_ms": statistics.median(times),
        "p95_ms": times[int(0.95 * (len(times) - 1))],
        "usd_per_line": statistics.mean(r["usd"] for r in rows),
        "fell_back": sum(1 for r in rows if r["fallback_from"]),
        "fallbacks": sorted({r["fallback_from"] for r in rows if r["fallback_from"]}),
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", nargs="*", default=["decisions", "responses"])
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}': add OPENAI_API_KEY to backend/.env.")
        return 1
    every = json.loads((ROOT / "evals" / "intent_cases.json").read_text(encoding="utf-8"))["cases"]
    cases = [c for c in every if intent.obvious(c["text"], bool(c["talking"])) is None]
    print(f"{len(cases)} of {len(every)} lines need the decider (code sorts the rest alone).")
    results = [run(backend, cases, args.runs) for backend in args.backend]
    for result in results:
        print(f"\n{result['backend']:10} right {result['right']}/{result['of']} ({result['accuracy']:.0%}) · "
              f"by kind {result['by_kind']} · p50 {result['p50_ms']:.0f} ms, p95 {result['p95_ms']:.0f} ms · "
              f"${result['usd_per_line']:.6f} a line · fell back {result['fell_back']}")
        for reason in result["fallbacks"][:5]:
            print(f"      fell back: {reason[:160]}")
        wrong = {}
        for r in result["rows"]:
            if not r["ok"]:
                wrong.setdefault(r["text"], []).append(r["got"])
        for text, got in wrong.items():
            print(f"      wrong {got} (expected {next(c['expect'] for c in cases if c['text'] == text)}): {text[:110]}")
    out = ROOT / "evals" / "results" / f"intent_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
