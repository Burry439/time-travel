"""Live evaluation of memory across conversations (GDD D-36), with the real models.

    backend/.venv/Scripts/python.exe evals/run_memory_evals.py

1. Tell Hessa a name and a trade, chat about other things, walk away; the conversation becomes an episode.
   Later, a new conversation: she must recall the name and the trade.
2. Tell Bren an obvious lie: it must be kept as a doubted claim and reach his next conversation.
3. Hessa meets Bren and tells him about the stranger: Bren must then know the name he never heard.
About two cents. Writes evals/results/memory_*.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import briefing  # noqa: E402
import cast  # noqa: E402
import persona  # noqa: E402
import routes_minds  # noqa: E402
import village  # noqa: E402
from ai import decider, voice  # noqa: E402
from run_talk_evals import exchange, world_for  # noqa: E402

FIRST = ["Hello! My name is Ash. I'm a healer from the south.", "I trade in herbs, mostly: feverfew and willow bark.",
         "The road here was long and muddy.", "Is the inn busy this time of year?", "Do many travellers come by?",
         "What's good to eat here?", "Thank you, that helps. I'll be off for now."]
LATER = ["Hello again! Do you remember me?", "What was it I told you I do for a living?"]


def recollect(state: dict, npc_id: str) -> str:
    person = cast.find(state["npcs"], npc_id)
    context, fallback = routes_minds._recollect_context(person)
    call, result = voice.recollect(context, fallback)
    routes_minds._apply_recollection(person, context, result, state["sim_time_ms"])
    state["sim_time_ms"] += 60_000
    return result["episode"]


def main() -> int:
    if decider.mode() != "llm":
        print("Needs OPENAI_API_KEY in backend/.env.")
        return 1
    report, failures = {}, []
    state, hessa = world_for({"npc": "npc_hessa_marr"})
    first = [exchange(state, hessa["id"], line) for line in FIRST]
    known = persona.knows(cast.find(state["npcs"], hessa["id"]))
    report["hessa_notes"] = list(known["notes"])
    if known.get("name") != "Ash":
        failures.append(f"Hessa didn't take the name: {known.get('name')}")
    report["hessa_episode"] = recollect(state, hessa["id"])
    later = [exchange(state, hessa["id"], line) for line in LATER]
    said_later = " ".join(t.get("line", "") for t in later).lower()
    if "ash" not in said_later:
        failures.append("Hessa didn't use the name in the later conversation")
    if not any(w in said_later for w in ("heal", "herb", "feverfew", "willow")):
        failures.append("Hessa didn't recall the trade")
    report["hessa_first"], report["hessa_later"] = first, later

    bren_id = "npc_bren_marr"
    bren = cast.find(state["npcs"], bren_id)
    state["player"].update(x=bren["x"], y=bren["y"] + 1)
    lie = exchange(state, bren_id, "I'm the king's own cousin, so you'd better let me through.")
    claims = persona.knows(cast.find(state["npcs"], bren_id))["claims"]
    if not claims:
        failures.append("Bren believed the king's-cousin story")
    recollect(state, bren_id)
    situation, _ = briefing.request(state, cast.find(state["npcs"], bren_id), "Well?")
    if claims and "didn't believe it" not in situation:
        failures.append("The doubted claim didn't reach Bren's next conversation")
    report["bren_lie"] = lie

    # Gossip: Hessa tells Bren about the stranger; he takes the name from her.
    persona.knows(cast.find(state["npcs"], bren_id))["name"] = None
    persona.knows(cast.find(state["npcs"], bren_id))["heard_name"] = None
    a, b = cast.find(state["npcs"], hessa["id"]), cast.find(state["npcs"], bren_id)
    text, questions = village.meet_brief(state, a, b)
    decided = decider.decide(text, questions)
    topic = (decided.answers.get("topic") or {}).get("choice")
    report["gossip_topic_chosen"] = topic
    answers = dict(decided.answers, topic={"choice": "stranger"})
    options = village.topics(state, a, b)
    call, lines = voice.chatter(village.chatter_context(state, a, b, options["stranger"], answers),
                                village.fallback_chatter(a, b, options["stranger"], answers))
    village.apply_meeting(state, a, b, answers, lines, state["sim_time_ms"])
    report["gossip_lines"] = lines
    if persona.knows(b).get("heard_name") != "Ash":
        failures.append(f"Bren didn't hear the name from Hessa (believes={answers.get('believes')})")
    reply = exchange(state, bren_id, "Have you heard of me?")
    report["bren_after_gossip"] = reply

    print("Hessa's notes:\n  " + "\n  ".join(report["hessa_notes"]))
    print(f"Hessa's episode: {report['hessa_episode']}")
    for turn in later:
        print(f"Later  you: {turn['said']}\n       Hessa: {turn.get('line')}")
    print(f"Bren on the lie: {lie.get('line')}  (claims kept: {len(claims)})")
    print(f"The decider's own topic choice for Hessa meeting Bren: {topic}")
    print(f"Gossip  Hessa: {lines[0]}\n        Bren:  {lines[1]}")
    print(f"Bren, asked 'Have you heard of me?': {reply.get('line')}")
    print("\n" + ("PASS" if not failures else "FAIL: " + "; ".join(failures)))
    out = ROOT / "evals" / "results" / f"memory_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({"failures": failures, **report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {out.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
