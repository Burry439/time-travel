"""Live check of awe and superstition (D-63): a superstitious person who saw something uncanny is afraid; does a
proper explanation turn their fear to wonder, and does bluster leave it as it was?

    backend/.venv/Scripts/python.exe evals/run_wonder_live.py [--runs 3]

Each case: the stranger floats a lodestone-rubbed needle that swings north, in front of a superstitious person
(fear, no awe: code, at first sight), then says one line to them. Scored on that person's own reading
(understood_the_wonder) in their own call: "explains" lines should win them over, the rest shouldn't. Prints each
reply. Writes evals/results/wonder_*.json. A few cents a run.
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
import encounter  # noqa: E402
import perception  # noqa: E402
import reputation  # noqa: E402
import rounds  # noqa: E402
from ai import config  # noqa: E402

SHOWN = {
    "event_id": 7,
    "category": "success",
    "action": "demonstrate",
    "property": [],
    "demonstration": {
        "object_id": "needle_x",
        "object_name": "floating needle",
        "used_ids": [],
        "audience_ids": [],
        "observed": "The stranger floated a needle on a leaf in a bowl of water; it swung round by itself and settled "
        "pointing north, every time they turned the bowl.",
        "works": True,
        "results": [],
        "wonder": "uncanny",
    },
}
EXPLAINS = [
    "It's no spell. I rubbed the needle on a lodestone, a stone that pulls iron. The needle takes on its pull, and "
    "the earth itself pulls it to point north. Here, rub this one yourself and watch it turn.",
    "Sailors far away use the same trick. A lodestone makes iron want to face north, nothing more. Floated on water "
    "it can turn freely, so it shows you which way north is, even in fog.",
]
DOESNT = [
    "It's a gift from the gods. Don't ask questions.",
    "Trust me, it's perfectly safe.",
    "Lovely weather today, isn't it?",
]
PEOPLE = ["npc_roderic_vale", "npc_mara_venn"]  # Both superstitious ("wary") by their cards.


def one(who: str, text: str) -> dict:
    state = app.initial_state(
        {"id": "wonder0", "mode": "developer", "seed_version": app.SEED_VERSION, "geometry_version": app.GEOMETRY_VERSION}
    )
    npc = cast.find(state["npcs"], who)
    state["player"].update(x=npc["x"], y=npc["y"] + 1)
    perception.apply_perceptions(state, perception.perceive(state, SHOWN))
    assert reputation.feared_wonders(npc), "a superstitious person who saw it should fear it"
    encounter.open_for_talk(state, npc, state["sim_time_ms"])
    moment = rounds.scene(state, who, text, None, True, nearby=[])
    call = moment["call"]
    if call.status != "ok" or not call.lines:
        return {"understood": None, "text": call.text, "error": call.error}
    line = call.lines[0]
    return {"understood": line["answers"].get("understood", {}).get("noul", 0) >= 0.5, "text": line["text"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    assert config.mode() == "live", "Needs OPENAI_API_KEY in backend/.env"
    results, right, total = [], 0, 0
    for who in PEOPLE:
        for text, wanted in [(t, True) for t in EXPLAINS] + [(t, False) for t in DOESNT]:
            got = [one(who, text) for _ in range(args.runs)]
            ok = sum(g["understood"] is wanted for g in got)
            right, total = right + ok, total + args.runs
            results.append({"who": who, "text": text, "wanted": wanted, "got": got})
            print(f"{'EXPLAINS' if wanted else 'NOT':8} {ok}/{args.runs}  {who[4:]:12} {text[:60]}")
            for g in got:
                print(f"           {str(g['understood']):5} {g['text'][:120]}")
    print(f"\nright: {right}/{total}")
    out = ROOT / "evals" / "results" / f"wonder_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
