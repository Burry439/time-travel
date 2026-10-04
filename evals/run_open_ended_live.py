"""Held-out open-ended scenarios through the real models and reducer, without touching saves."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import agreements
import attempts
import briefing
import cast
import consequences
import judge_view
import store
from ai import config, voice


def world():
    state = store.initial_state(
        {
            "id": "heldout",
            "mode": "developer",
            "seed_version": store.SEED_VERSION,
            "geometry_version": store.GEOMETRY_VERSION,
        }
    )
    state["player"].update(x=40, y=40)
    for oid in ("branch_a", "flint_a", "vine_a", "gourd_a"):
        state["objects"][oid].update(holder_id="player", owner_id="player")
    state["objects"]["gourd_a"]["water_l"] = 0.1
    return state


def physical(state, name, text, success):
    started = time.monotonic()
    token = config.deadline.set(started + 15)
    try:
        context = judge_view.build_context(state, text, [])
        call = attempts.judge_attempt(context, 0)
        payload, result, _ = consequences.resolve_attempt(
            state,
            state["run_id"],
            text,
            call.result,
            attempts.service_message(call),
            "heldout",
            state["sim_time_ms"],
        )
        consequences.apply_payload(state, payload)
    finally:
        config.deadline.reset(token)
    passed = (
        result["category"] in ("success", "partial_success")
    ) == success and call.result is not None
    return {
        "name": name,
        "passed": passed,
        "seconds": round(time.monotonic() - started, 2),
        "category": result["category"],
        "reason": result["reason"],
        "notes": result["notes"],
        "model": call.model,
        "error": call.error,
        "proposal": call.result,
    }


def person(state, npc_id, text, name):
    npc = cast.find(state["npcs"], npc_id)
    npc.update(x=41, y=40)
    context = briefing.scene_context(state, npc, [npc], [], text, None)
    started = time.monotonic()
    token = config.deadline.set(started + 8)
    try:
        call = voice.scene(context, "", allowed=True)
    finally:
        config.deadline.reset(token)
    return {
        "name": name,
        "passed": call.status == "ok",
        "seconds": round(time.monotonic() - started, 2),
        "lines": call.lines,
        "error": call.error,
        "model": call.model,
    }, call.lines


def run():
    if config.mode() != "live":
        raise SystemExit(
            "Live AI is unavailable. Configure backend/.env; no credentials are printed."
        )
    state = world()
    rows = [
        physical(
            state,
            "novel_groove",
            "Using my flint, carve a shallow spiral groove around the branch, with regular tick marks along it. Keep the same stick; the groove is a guide for drops of water.",
            True,
        )
    ]
    attrs = state["objects"]["branch_a"].get("attributes", [])
    made = [o for o in state["objects"].values() if o.get("created_by") == "player"]
    rows[0]["persisted_novel_attributes"] = bool(
        attrs or any(o.get("attributes") for o in made)
    )
    rows[0]["passed"] &= rows[0]["persisted_novel_attributes"]
    if rows[0]["passed"]:
        rows.append(
            physical(
                state,
                "reuse_groove",
                "Put a few drops from my gourd at the top of the spiral groove I just carved, then tilt the stick slowly so the water follows that groove. Observe whether it runs along the channel.",
                True,
            )
        )
    rows.append(
        physical(
            world(),
            "absurd_capacity",
            "Carve my small branch into a wooden tank that holds one hundred thousand litres of water without collapsing. I have only my flint and branch.",
            False,
        )
    )
    state = world()
    bronze = copy.deepcopy(state["objects"]["flint_a"])
    bronze.update(
        id="bronze_ring",
        name="bronze ring",
        materials=["bronze"],
        flags=["rigid"],
        mass_kg=0.02,
    )
    state["objects"]["bronze_ring"] = bronze
    state["objects"]["lodestone_darin"].update(holder_id="player", owner_id="player")
    rows.append(
        physical(
            state,
            "bronze_magnet",
            "Rub my bronze ring on the lodestone until the bronze itself becomes a strong permanent magnet. Do not add iron or any other material.",
            False,
        )
    )
    state = world()
    helper = cast.find(state["npcs"], "npc_tomas_reed")
    helper.update(x=41, y=40)
    helper.setdefault("mind", {}).setdefault("regard", {})["trust"] = 1
    rows.append(
        physical(
            state,
            "uncommitted_helper",
            "Have Tomas do all the work forging a precision steel watch mechanism for me. I have not asked him and have only my branch, flint and vine.",
            False,
        )
    )
    state = world()
    row, lines = person(
        state,
        "npc_hessa_marr",
        "Could we agree on a new job? I will build a rain-shielded sign holder for your inn, and show you that a wet sign stays readable. In return I want your wooden bowl. Please offer that arrangement if it suits you.",
        "negotiated_task",
    )
    if lines:
        proposal = lines[0].get("agreement")
        row["negotiated"] = bool(
            proposal
            and proposal["action"] == "offer"
            and "sign" in proposal["task"].lower()
        )
        if proposal:
            row["accepted_by_reducer"], row["detail"] = agreements.apply(
                state, cast.find(state["npcs"], "npc_hessa_marr"), proposal, 1
            )
        row["passed"] &= row["negotiated"] and row.get("accepted_by_reducer", False)
    rows.append(row)
    state = world()
    row, lines = person(
        state,
        "npc_oren_dast",
        "Darin's debt can ruin you. If you quietly let me through, I will speak to him about paying it. I know this is an exception; you can refuse if protecting the gate matters more.",
        "individual_duty_exception",
    )
    row["choice"] = lines[0]["move"] if lines else None
    row["passed"] &= bool(lines and lines[0].get("remember"))
    rows.append(row)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    results = []
    for repetition in range(args.runs):
        for row in run():
            row["run"] = repetition + 1
            results.append(row)
            print(
                json.dumps(
                    {
                        k: row.get(k)
                        for k in (
                            "name",
                            "run",
                            "passed",
                            "seconds",
                            "category",
                            "choice",
                            "error",
                        )
                    }
                ),
                flush=True,
            )
    path = (
        ROOT
        / "evals/results"
        / (
            "open_ended_"
            + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
    )
    path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"REPORT: {path}")
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)
