"""Live combat checks: real judge/person calls, deterministic reducer, no image generation.
Run with IMAGES=off; writes only evals/results. No player database is opened.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["IMAGES"] = "off"
import app
import cast
import combat
import consequences
import effects
import gear
import judge_view
import minds
import routes_minds
from ai import config, judge


def fresh(npc_id: str) -> dict:
    state = app.initial_state({"id": "combat-eval", "mode": "developer", "seed_version": app.SEED_VERSION,
                               "geometry_version": app.GEOMETRY_VERSION})
    person = cast.find(state["npcs"], npc_id)
    state["player"].update(x=person["x"], y=person["y"] + 1)
    return state


def described(case: str, bound: bool = False, damaged: bool = False) -> dict:
    state = fresh("npc_tomas_reed")
    blade = state["objects"]["knife_darin"] if "knife_darin" in state["objects"] else next(
        o for o in state["objects"].values() if gear.of(o).get("class") == "knife")
    blade.update(holder_id="player", owner_id="player")
    gear.equip(state, state["player"], blade, "right")
    if bound:
        effects.put_state(state["player"], "bound", "hands tied", ["hands"], 10, 0, "eval")
    if damaged:
        effects.apply(state, [{"kind": "damage", "target_id": blade["id"], "name": "blunted",
                               "flags": ["sharp_edge"]}], 0, "player", lambda _obj: None)
    text = "I drive the knife in my right hand into Tomas's side."
    call = judge.judge_craft(judge_view.build_context(state, text, [blade["id"]]))
    if call.status != "ok":
        return {"case": case, "ok": False, "error": call.error}
    _, summary, after = consequences.resolve_attempt(state, "combat-eval", text, call.result, None, "eval", 0)
    harm = summary.get("harm") or {}
    target = cast.find(after["npcs"], "npc_tomas_reed")
    ok = summary["category"] in ("blocked", "failed") and target["health"] == 100 if bound else (
        harm.get("result") in ("wounded", "deflected", "missed", "knocked_out") and gear.weapon(blade)["type"] == "blunt")
    return {"case": case, "ok": ok, "category": summary["category"], "reason": summary["reason"],
            "harm": harm, "health": target["health"], "profile": gear.weapon(blade)}


def reaction(case: str, npc_id: str, health: float, why: str) -> dict:
    state = fresh(npc_id)
    person = cast.find(state["npcs"], npc_id)
    combat.start(state, [npc_id], 0, "eval")
    person["health"] = health
    person["injuries"] = [why]
    if case == "ally_falls":
        ally = cast.find(state["npcs"], "npc_elin_west")
        ally.update(x=person["x"] + 1, y=person["y"], down=True, health=0)
    call = routes_minds._personal_reaction(state, {"npc_id": npc_id, "kind": "decide", "why": why})
    decision = call.answers.get("npc_decision") or {}
    legal = minds.legal_actions(state, person)
    if not call.error and decision:
        minds.apply_decision(state, person, call.answers, 0, state["journal"])
        combat.tick(state, state["npcs"], 1, 0, __import__("paths").grid(state), state["journal"])
    return {"case": case, "ok": not call.error and decision.get("move") in legal,
            "move": decision.get("move"), "text": decision.get("text"), "job": cast.mind(person).get("job"),
            "still_fighting": combat.fighting(state, person), "latency_ms": call.latency_ms, "error": call.error}


def main() -> int:
    if config.mode() != "live":
        print("Live models are not configured.")
        return 1
    out = ROOT / "evals" / "results" / f"combat_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    report = []
    cases = [("bound_described_attack", lambda: described("bound_described_attack", bound=True)),
             ("blunted_described_attack", lambda: described("blunted_described_attack", damaged=True)),
             ("guard_injured", lambda: reaction("guard_injured", "npc_bren_marr", 35, "hurt badly in the fight")),
             ("smith_injured", lambda: reaction("smith_injured", "npc_mara_venn", 25, "hurt badly in the fight")),
             ("ally_falls", lambda: reaction("ally_falls", "npc_kade_east", 55, "Elin fell beside you"))]
    for name, run in cases:
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        try:
            report.append(run())
        except Exception as error:
            report.append({"case": name, "ok": False, "error": f"{type(error).__name__}: {error}"})
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf8")
    for result in report:
        print("PASS" if result["ok"] else "FAIL", result["case"], result.get("category", result.get("move")),
              str(result.get("reason", result.get("text", "")))[:140])
    print(f"{sum(r['ok'] for r in report)}/{len(report)} passed; {out.relative_to(ROOT)}")
    return 0 if all(r["ok"] for r in report) else 1

if __name__ == "__main__":
    raise SystemExit(main())
