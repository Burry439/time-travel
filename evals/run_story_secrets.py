"""Live check of the storylines' people (D-61): do people confide a secret, or agree to what a story lets them,
when the moment calls for it and only then? And does the reading beside the conversation tell passing a secret on
from hinting at it?

    backend/.venv/Scripts/python.exe evals/run_story_secrets.py [--runs 3]

Each case puts the stranger beside someone in the village where code already allows the move (trust high enough,
the right thing known), says one line, and checks the move that person picked in their own call: "should" lines
ask for it or touch it, "should not" lines are about something else. The told cases call the reading directly with
the secrets the stranger knows. Writes evals/results/story_secrets_*.json. A few cents a run.
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
import conversation  # noqa: E402
import encounter  # noqa: E402
import persona  # noqa: E402
import reputation  # noqa: E402
import rounds  # noqa: E402
import stories  # noqa: E402
from ai import config, voice  # noqa: E402


def village() -> dict:
    return app.initial_state(
        {
            "id": "secrets0",
            "mode": "developer",
            "seed_version": app.SEED_VERSION,
            "geometry_version": app.GEOMETRY_VERSION,
        }
    )


def learn(state: dict, **entry) -> None:
    state.setdefault("learned", []).append(
        {"npc_id": "npc_hessa_marr", "lead": "…", **entry}
    )


def known_a_while(npc: dict, episode: str, help_summary: str | None = None) -> None:
    """Trust as it really comes: a name given, an earlier conversation, and (if any) help remembered."""
    persona.knows(npc).update(name="Ash", episodes=[{"text": episode, "at": 0}])
    if help_summary:
        cast.mind(npc)["memories"].append(
            {
                "kind": "help",
                "victim": npc["id"],
                "item": None,
                "clarity": "clear",
                "source": "received",
                "at": 0,
                "event": 1,
                "summary": help_summary,
                "short": "helped me",
                "severity": 1,
            }
        )


def bren(state: dict) -> None:
    who = cast.find(state["npcs"], "npc_bren_marr")
    reputation.regard(who).update(
        trust=0.55, suspicion=0.25
    )  # Help that earns trust eases suspicion too.
    known_a_while(
        who,
        "Ash hauled water for Hessa's kitchen all morning and wouldn't take a coin; we talked about the long watches.",
        "Ash hauled water for Hessa's kitchen, unasked, and wouldn't take payment.",
    )


def darin(state: dict) -> None:
    learn(state, fact="oren_debt")
    who = cast.find(state["npcs"], "npc_darin_ko")
    reputation.regard(who).update(trust=0.6, suspicion=0.3)
    known_a_while(
        who,
        "Ash and I talked trade over supper at the inn; sharp, and honest about prices.",
    )


def darin_paid(state: dict) -> None:
    """The stranger has already given Darin something he can sell: his price, met."""
    darin(state)
    state["objects"]["compass_gift"] = {
        **state["objects"]["branch_a"],
        "id": "compass_gift",
        "name": "floating compass",
        "materials": ["iron", "wood"],
        "description": "A magnetised needle on a cork in a wooden bowl of water; it swings to point north.",
        "flags": ["magnetized", "indicates_direction"],
        "holder_id": "npc_darin_ko",
        "owner_id": "npc_darin_ko",
        "given_by": "player",
        "gear": None,
    }
    cast.mind(cast.find(state["npcs"], "npc_darin_ko"))["memories"].append(
        {
            "kind": "gift",
            "victim": "npc_darin_ko",
            "item": "floating compass",
            "clarity": "clear",
            "works": True,
            "source": "received",
            "at": 0,
            "event": 1,
            "short": "gave me a compass that finds north",
            "severity": 1,
            "summary": "Ash gave Darin a working compass, a magnetised needle in a bowl, to copy and sell in the city.",
        }
    )


def hessa(state: dict) -> None:
    learn(state, fact="sick_guests")
    cast.mind(cast.find(state["npcs"], "npc_hessa_marr"))["memories"].append(
        {
            "kind": "demonstration",
            "victim": None,
            "item": "pot of boiled water",
            "clarity": "clear",
            "works": True,
            "source": "shown",
            "at": 0,
            "event": 1,
            "short": "boiled the trough water",
            "severity": 1,
            "summary": "The stranger boiled trough water in a pot and showed that boiled water keeps people well.",
        }
    )


# (who, set-up, the move code allows, should lines, should-not lines). "Should" lines ask about the very thing, or
# meet the person's own price; "should not" lines are about something else, or ask without meeting it (Darin asked
# kindly, with nothing on the table, names his price instead: that's him deciding, as he should).
MOVES = [
    (
        "npc_bren_marr",
        bren,
        "confide:bren_covers_oren",
        [
            "Someone must be standing Oren's watches when he doesn't show. Is it you?",
            "Who's been covering Oren's missed watches? The captain will notice sooner or later.",
        ],
        [
            "Nice weather today.",
            "Where can I buy bread around here?",
            "Who's the captain here?",
        ],
    ),
    (
        "npc_darin_ko",
        darin,
        "story:forgive_oren_debt",
        [],
        [
            "What are you selling?",
            "Have you heard any news from the city?",
            "Oren can't pay you back. Would you let the debt go? It'd mean a lot to him.",
        ],
    ),
    (
        "npc_darin_ko",
        darin_paid,
        "story:forgive_oren_debt",
        [
            "You've got the compass now. Square it with me: let Oren's debt go.",
            "That compass is yours to keep and copy. All I ask in return: let Oren off his debt.",
        ],
        [],
    ),
    (
        "npc_hessa_marr",
        hessa,
        "story:trust_clean_water",
        [
            "Boil the trough water before your guests drink it, like I showed you. Will you do that?"
        ],
        ["How much for a room?", "Is your brother on watch today?"],
    ),
]

TOLD = [
    ("Tomas cracked the first beam himself, rushing the job.", ["tomas_cracked"]),
    (
        "Captain, your carpenter broke the old beam by hurrying it. That's why it's cracked.",
        ["tomas_cracked"],
    ),
    ("Between us, Oren owes Darin eleven silver from dice.", ["oren_debt"]),
    ("Have you asked Tomas how the beam cracked?", []),
    ("I know something about Tomas, but it's not mine to tell.", []),
    ("Oren seems jumpy lately.", []),
    ("Is Oren in some kind of trouble?", []),
    ("Good morning, captain. Any work going?", []),
]


def one_move(who: str, setup, allowed: str, text: str) -> dict:
    state = village()
    setup(state)
    npc = cast.find(state["npcs"], who)
    assert allowed in conversation.replies(state, npc), (who, allowed)
    state["player"].update(x=npc["x"], y=npc["y"] + 1)
    encounter.open_for_talk(state, npc, state["sim_time_ms"])
    started = time.perf_counter()
    moment = rounds.scene(state, who, text, None, True, nearby=[])
    call = moment["call"]
    line = (
        call.lines[0]
        if call.status == "ok" and call.lines
        else {"move": "(fallback)", "text": call.text}
    )
    return {
        "move": line.get("move"),
        "text": line.get("text"),
        "ms": round((time.perf_counter() - started) * 1000),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    assert config.mode() == "live", "Needs OPENAI_API_KEY in backend/.env"
    results, right, total = {"moves": [], "told": []}, 0, 0
    for who, setup, allowed, should, should_not in MOVES:
        for text, wanted in [(t, True) for t in should] + [
            (t, False) for t in should_not
        ]:
            made = [one_move(who, setup, allowed, text) for _ in range(args.runs)]
            hits = sum(m["move"] == allowed for m in made)
            ok = hits if wanted else args.runs - hits
            right, total = right + ok, total + args.runs
            results["moves"].append(
                {
                    "who": who,
                    "move": allowed,
                    "text": text,
                    "wanted": wanted,
                    "made": made,
                }
            )
            print(
                f"{'SHOULD' if wanted else 'NOT':6} {ok}/{args.runs}  {who:18} {text[:60]}"
            )
            for m in made:
                print(f"         {m['move']:28} {m['text'][:110]}")
    state = village()
    learn(state, secret="tomas_cracked", npc_id="npc_tomas_reed")
    learn(state, secret="oren_debt", npc_id="npc_oren_dast")
    roderic = cast.find(state["npcs"], "npc_roderic_vale")
    could = stories.tellable(state, [roderic])
    told_right = 0
    for text, wanted in TOLD:
        got = [
            voice.told(
                {"stranger_says": text, "told_to": ["Roderic"], "could_pass_on": could}
            )[1]
            for _ in range(args.runs)
        ]
        ok = sum(sorted(g) == sorted(wanted) for g in got)
        told_right += ok
        results["told"].append({"text": text, "wanted": wanted, "got": got})
        print(f"TOLD   {ok}/{args.runs}  {text[:70]:70} {got[0]}")
    told_total = len(TOLD) * args.runs
    print(f"\nmoves right: {right}/{total}   told right: {told_right}/{told_total}")
    out = (
        ROOT
        / "evals"
        / "results"
        / f"story_secrets_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
