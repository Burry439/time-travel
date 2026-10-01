"""Live evaluation of how distinct the characters sound (GDD D-38).

    backend/.venv/Scripts/python.exe evals/run_persona_evals.py [--baseline]

The same six stranger lines go to each of the ten people, with the reply fixed to "answer" so only the
voice is measured. A Luna judge sees each line with short descriptions of all ten people and must name
the speaker. --baseline measures the previous voice (voice_v2, style string only) on the same lines.
Needs OPENAI_API_KEY in backend/.env; costs about three cents. Writes evals/results/persona_*.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app  # noqa: E402
import briefing  # noqa: E402
import cast  # noqa: E402
from ai import config, voice  # noqa: E402

LINES = ["Good day. I'm new here; what is this place?", "Could you use a hand with anything?",
         "What do you make of the captain?", "I need to get into the city. Any advice?",
         "Fine weather, isn't it?", "Why should I trust you?"]
V2 = (ROOT / "backend" / "prompts" / "voice_v2.txt").read_text(encoding="utf-8")
V2_FIELDS = ("character", "regard_for_the_stranger", "what_they_know", "keeps_to_themselves", "conversation_so_far",
             "stranger_says", "what_just_happened", "decided_reply", "also_decided")


class Guess(BaseModel):
    speaker: str


class _Line(BaseModel):
    text: str


def world() -> dict:
    state = app.initial_state({"id": "persona", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION})
    state.setdefault("pending_minds", [])
    return state


def line_for(state: dict, npc: dict, text: str, baseline: bool) -> str:
    person = cast.find(state["npcs"], npc["id"])
    state["player"].update(x=person["x"], y=person["y"] + 1)
    context = briefing.voice_context(state, person, text, "answer", {})
    if not baseline:
        return voice.speak(context, "").text
    old = {k: context[k] for k in V2_FIELDS}
    old["speaking_style"] = cast.card(person).get("style", "")
    response = config.client().responses.parse(
        model=config.voice_model(), reasoning={"effort": config.voice_reasoning()}, store=False,
        text_format=_Line,
        input=[{"role": "developer", "content": V2},
               {"role": "user", "content": json.dumps(old, indent=1, ensure_ascii=False)}])
    return voice.tidy(response.output_parsed.text)


def judge(cast: str, names: list[str], text: str, line: str) -> str:
    response = config.client().responses.parse(
        model=config.voice_model(), reasoning={"effort": "low"}, store=False, text_format=Guess,
        input=[{"role": "developer", "content": "Ten people live in a small town. Read who they are, then say which "
                                                 f"one said the reply. Answer with one name from: {', '.join(names)}."},
               {"role": "user", "content": f"THE PEOPLE\n{cast}\n\nA stranger said: “{text}”\nThe reply: “{line}”"}])
    return response.output_parsed.speaker.strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args(argv)
    if config.mode() != "live":
        print("Add OPENAI_API_KEY to backend/.env.")
        return 1
    state = world()
    people = state["npcs"]
    names = [n["name"] for n in people]
    # The judge knows each person as a townsfolk would: who they are and how they talk (the same in both conditions).
    cast = "\n".join(f"- {n['name']}, {cast.card(n)['role']}: {cast.card(n)['personality']} Talks: "
                     f"{cast.card(n)['style']}" for n in people)
    jobs = [(n, text) for n in people for text in LINES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        lines = list(pool.map(lambda job: line_for(world(), job[0], job[1], args.baseline), jobs))
        guesses = list(pool.map(lambda pair: judge(cast, names, pair[0][1], pair[1]), zip(jobs, lines)))
    rows = [{"npc": n["name"], "stranger": text, "line": line, "guess": guess, "right": guess == n["name"]}
            for (n, text), line, guess in zip(jobs, lines, guesses)]
    right = sum(r["right"] for r in rows)
    openings = Counter(" ".join(r["line"].lower().split()[:2]) for r in rows)
    shared = sum(1 for r in rows if openings[" ".join(r["line"].lower().split()[:2])] > 1)
    by_person = {name: sum(r["right"] for r in rows if r["npc"] == name) for name in names}
    label = "baseline (voice_v2, style only)" if args.baseline else "character sheets (voice_v3)"
    print(f"{label}: speaker identified {right}/{len(rows)} ({100 * right / len(rows):.0f}%) · lines sharing their "
          f"first two words with another: {shared}/{len(rows)}")
    print("  per person: " + ", ".join(f"{k} {v}/{len(LINES)}" for k, v in by_person.items()))
    for row in rows[:: len(LINES)]:
        print(f"  {row['npc']:8} “{row['line']}”")
    out = ROOT / "evals" / "results" / f"persona_{'baseline_' if args.baseline else ''}{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"label": label, "identified": right, "total": len(rows), "shared_openings": shared,
                               "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # The reports quote words; a Windows console would refuse them.
    raise SystemExit(main(sys.argv[1:]))
