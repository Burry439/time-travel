"""Crafting slice: the judge is stubbed, so these test what code allows and commits."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as service
import cast
import consequences
import crafting
import judge_view
import tuning
from ai import illustrator, judge

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4b70000000049454e44ae426082"
)


def spear_step(**changes):
    step = {
        "action": "make",
        "outcome": "success",
        "reason": "You lash the flint to the branch.",
        "effort_seconds": 40,
        "take_ids": [],
        "transformation": None,
        "harm": None,
        "new_object": {
            "name": "flint-tipped spear",
            "description": "A branch with a flint point lashed on.",
            "materials": ["wood", "flint", "vine"],
            "consumes": ["branch_a", "flint_a", "vine_a"],
            "tools_used": [],
            "mass_kg": 1.9,
            "length_m": 1.6,
            "capacity_l": None,
            "rated_load_kg": None,
            "flags": ["rigid", "sharp_edge"],
            "capabilities": [{"text": "can pierce soft things", "status": "expected"}],
        },
    }
    for key, value in changes.items():
        if key in step["new_object"]:
            step["new_object"][key] = value
        elif key != "clarifying_question":
            step[key] = value
    return step


def attempt(*steps, question=None, key="test"):
    """A judge reply in the multi-step format."""
    return {"clarifying_question": question, "precedent_key": key, "steps": list(steps)}


def spear(**changes):
    if changes.get("outcome") == "needs_clarification":
        return attempt(question=changes.get("clarifying_question", "Which one?"))
    return attempt(spear_step(**changes), key="lash:flint+branch|vine")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(service.store, "DB_PATH", tmp_path / "craft.sqlite3")
    monkeypatch.setattr(service.attempts, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setattr(service.ai_config, "images_enabled", lambda: True)
    painted = []

    def fake_sprite(record, destination: Path):
        painted.append(record)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(PNG)
        return illustrator.SpriteCall(status="ready", model="stub-image", prompt=illustrator.sprite_prompt(record))

    monkeypatch.setattr(service.illustrator, "generate_sprite", fake_sprite)
    ns = SimpleNamespace(contexts=[], replies=[], painted=painted, http=TestClient(service.app))

    def fake_judge(context):
        ns.contexts.append(context)
        return judge.JudgeCall(status="ok", result=ns.replies.pop(0), model="stub", raw_output="{...}", attempts=1)

    monkeypatch.setattr(service.judge, "judge_craft", fake_judge)
    return ns


def walk_to(http, state, x, y):
    while (state["player"]["x"], state["player"]["y"]) != (x, y):
        px, py = state["player"]["x"], state["player"]["y"]
        step = {
            "x": px + (x > px) - (x < px),
            "y": py + (y > py) - (y < py),
            "expected_version": state["event_seq"],
            "request_id": f"walk-{state['event_seq']}",
        }
        response = http.post(f"/runs/{state['run_id']}/move", json=step)
        assert response.status_code == 200, response.text
        state = response.json()["state"]
    return state


def craft(http, state, text, request_id, selected=()):
    return http.post(
        f"/runs/{state['run_id']}/craft",
        json={
            "text": text,
            "selected_ids": list(selected),
            "expected_version": state["event_seq"],
            "request_id": request_id,
        },
    )


def test_success_creates_a_persistent_object_with_provenance_and_sprite(world):
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
    world.replies.append(spear())
    reply = craft(http, state, "lash the flint to the branch with the vine", "spear")
    assert reply.status_code == 200, reply.text
    body = reply.json()
    state = body["state"]
    made = state["objects"]["made_" + str(state["event_seq"])]
    assert made["holder_id"] == "player" and made["owner_id"] == "player"
    assert made["components"] == ["branch_a", "flint_a", "vine_a"]
    assert all(state["objects"][i]["holder_id"] == f"in:{made['id']}" for i in made["components"])
    assert made["created_text"] == "lash the flint to the branch with the vine"
    assert state["last_action"]["category"] == "success" and state["sim_time_ms"] == 40_000
    # Owned items never reach the judge; the context lists only reachable public or carried items.
    offered = {item["id"] for item in world.contexts[0]["available_items"]}
    assert "bucket_hessa" not in offered and {"flint_a", "branch_a", "vine_a"} <= offered
    # Developer runs get the full trace inline.
    assert body["trace"]["judge"]["raw_output"] == "{...}" and body["trace"]["made"] == made["id"]
    # The sprite painted from the validated record, not raw text, and is served.
    assert world.painted[0]["name"] == "flint-tipped spear"
    picture = http.get(f"/assets/{made['sprite_asset_id']}")
    assert picture.status_code == 200 and picture.content == PNG
    # Replay after reload and checkpoint is identical.
    assert http.get(f"/runs/{state['run_id']}").json() == state
    http.post(f"/runs/{state['run_id']}/checkpoint")
    assert http.get(f"/runs/{state['run_id']}").json() == state
    # Idempotent retry returns the same result without calling the judge again.
    retry = craft(
        http, {"run_id": state["run_id"], "event_seq": 0}, "lash the flint to the branch with the vine", "spear"
    )
    assert retry.json()["duplicate"] and retry.json()["state"] == state and len(world.contexts) == 1
    # The created object works with the quick actions (decided in code, no model).
    dropped = http.post(
        f"/runs/{state['run_id']}/quick",
        json={"verb": "drop", "object_id": made["id"], "expected_version": state["event_seq"], "request_id": "drop"},
    ).json()["state"]
    assert dropped["objects"][made["id"]]["holder_id"] is None
    assert (dropped["objects"][made["id"]]["x"], dropped["objects"][made["id"]]["y"]) == (
        dropped["player"]["x"],
        dropped["player"]["y"],
    )
    taken = http.post(
        f"/runs/{state['run_id']}/quick",
        json={"verb": "take", "object_id": made["id"], "expected_version": dropped["event_seq"], "request_id": "take"},
    ).json()["state"]
    assert taken["objects"][made["id"]]["holder_id"] == "player"
    assert http.get(f"/runs/{state['run_id']}").json() == taken
    assert len(world.contexts) == 1  # Neither quick action asked the judge.
    traces = http.get(f"/runs/{state['run_id']}/traces").json()
    assert traces["traces"][0]["request_id"] == "spear" and traces["assets"][0]["status"] == "ready"


@pytest.mark.parametrize(
    "change, note",
    [
        ({"consumes": ["bucket_hessa"]}, "not available"),
        ({"consumes": ["flint_a", "made_up_iron"]}, "not available"),
        ({"consumes": []}, "at least one consumed item"),
    ],
)
def test_invalid_proposals_change_nothing(world, change, note):
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
    world.replies.append(spear(**change))
    body = craft(http, state, "make a spear", "bad").json()
    after = body["state"]
    assert after["last_action"]["category"] == "unresolved"
    assert after["objects"] == state["objects"] and after["sim_time_ms"] == state["sim_time_ms"]
    assert any(note in n for n in body["trace"]["validator"]["notes"])


def test_validator_clamps_mass_strips_invented_material_and_unearned_flags(world):
    http = world.http
    state = walk_to(http, http.post("/runs", json={}).json(), 45, 66)
    world.replies.append(
        spear(
            materials=["wood", "flint", "vine", "iron"],
            mass_kg=50.0,
            flags=["sharp_edge", "magnetized", "light_source", "ferromagnetic"],
        )
    )
    state = craft(http, state, "make a magic glowing spear", "clamp").json()["state"]
    made = next(o for o in state["objects"].values() if o["id"].startswith("made_"))
    assert "iron" not in made["materials"]
    assert made["mass_kg"] == pytest.approx(1.2 + 0.3 + 0.4)
    assert made["flags"] == ["sharp_edge"]
    assert {c["text"] for c in made["known_capabilities"] if c["status"] == "untested"} >= {
        "could give light if lit",
        "might become magnetic if touched to a real magnet",
    }


@pytest.mark.parametrize("outcome", ["failed", "blocked", "unsupported", "needs_clarification"])
def test_non_success_outcomes_create_nothing(world, outcome):
    http = world.http
    state = walk_to(http, http.post("/runs", json={}).json(), 45, 66)
    world.replies.append(spear(outcome=outcome, clarifying_question="Which end?"))
    body = craft(http, state, "turn the stone into a magnet", "no").json()
    after = body["state"]
    assert after["objects"] == state["objects"]
    assert after["last_action"]["category"] == outcome
    assert (after["sim_time_ms"] > state["sim_time_ms"]) == (outcome == "failed")
    assert "trace" not in body  # Normal runs never expose AI internals.


def test_disabled_ai_is_honest_and_older_journeys_are_refused(world, monkeypatch):
    http = world.http
    monkeypatch.setattr(service.judge, "judge_craft", lambda context: judge.JudgeCall(status="disabled"))
    state = http.post("/runs", json={}).json()
    after = craft(http, state, "make a spear", "offline").json()["state"]
    assert after["last_action"]["category"] == "unresolved"
    assert "OPENAI_API_KEY" in after["last_action"]["reason"] and after["objects"] == state["objects"]
    assert http.get(f"/runs/{state['run_id']}/traces").status_code == 403
    with service.db() as connection:
        connection.execute("UPDATE runs SET seed_version=3 WHERE id=?", (state["run_id"],))
    retired = http.get(f"/runs/{state['run_id']}")
    assert retired.status_code == 410 and "Start a new journey" in retired.json()["detail"]


def test_new_road_materials_are_reachable_and_described():
    objects = service.m2.seed_objects({"scenario": "village", "npcs": []})
    for oid in ("flint_a", "stone_b", "grass_a", "reeds_a", "vine_a", "bark_a", "resin_a"):
        assert objects[oid]["owner_id"] is None and objects[oid]["materials"]
    assert consequences.placeholder_category(["flint"]) == "stone"


def test_stub_mode_runs_the_real_pipeline_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr(service.store, "DB_PATH", tmp_path / "stub.sqlite3")
    monkeypatch.setattr(service.attempts, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setenv("AI_MODE", "stub")
    http = TestClient(service.app)
    assert http.get("/health").json()["ai"]["mode"] == "stub"
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
    body = craft(http, state, "bundle these", "stub", selected=["flint_a", "vine_a"]).json()
    made = body["state"]["objects"][body["trace"]["made"]]
    assert made["components"] == ["flint_a", "vine_a"] and body["trace"]["judge"]["model"] == "stub"
    assert http.get(f"/assets/{made['sprite_asset_id']}").status_code == 200


# --- Try Something beyond making things (judge v2) ---------------------------------------


def fresh_state(x=48, y=68):
    state = service.initial_state(
        {
            "id": "unit0000",
            "mode": "developer",
            "seed_version": service.SEED_VERSION,
            "geometry_version": service.GEOMETRY_VERSION,
        }
    )
    state["player"].update(x=x, y=y)
    return state


def judged(action, **fields):
    base = {
        "action": action,
        "outcome": "success",
        "reason": "It happens.",
        "effort_seconds": 5,
        "clarifying_question": None,
        "precedent_key": action,
        "new_object": None,
        "take_ids": [],
        "transformation": None,
        "harm": None,
    }
    base.update(fields)
    return base


def commit(state, *steps, text="try"):
    """Resolve judge steps the way the /craft endpoint does and apply them to state."""
    payload, summary, after = consequences.resolve_attempt(
        state, "unit0000", text, attempt(*steps), None, "trace", state["sim_time_ms"]
    )
    payload["npcs"] = after["npcs"]
    state["event_seq"] += 1
    consequences.apply_payload(state, payload)
    return summary


def test_other_peoples_property_is_offered_usable_and_recorded():
    state = fresh_state(63, 28)  # Beside Tomas's plank at (64, 28).
    offered = {i["id"]: i for i in judge_view.build_context(state, "x", [])["available_items"]}
    assert offered["wood_tomas"]["belongs_to"] == "Tomas" and offered["wood_tomas"]["portable"]
    shield = {
        "name": "plank shield",
        "description": "A plank.",
        "materials": ["wood"],
        "consumes": ["wood_tomas"],
        "tools_used": [],
        "mass_kg": 4.0,
        "length_m": None,
        "capacity_l": None,
        "rated_load_kg": None,
        "flags": ["rigid"],
        "capabilities": [],
    }
    verdict = crafting.validate(state, judged("make", new_object=shield))
    assert verdict["category"] == "success"
    assert verdict["property"] == [
        {"id": "wood_tomas", "name": "wood plank", "owner_id": "npc_tomas_reed", "how": "used up"}
    ]
    taken = crafting.validate(fresh_state(63, 28), judged("take", take_ids=["wood_tomas"]))
    assert taken["category"] == "success" and taken["property"][0]["how"] == "taken"


def test_take_respects_reach_portability_and_weight():
    state = fresh_state()
    verdict = commit(state, judged("take", take_ids=["branch_a", "cord_a"]))
    assert verdict["category"] == "success"
    assert state["objects"]["branch_a"]["holder_id"] == "player" and state["objects"]["cord_a"]["holder_id"] == "player"
    assert crafting.validate(state, judged("take", take_ids=["log_a"]))["category"] == "unresolved"  # Out of reach.
    near_log = fresh_state(69, 60)
    blocked = crafting.validate(near_log, judged("take", take_ids=["log_a"]))
    assert blocked["category"] == "blocked" and "can't be picked up" in blocked["reason"]


def tree_felling(target="tree_01"):
    def piece(name, count, mass, flags=("rigid",)):
        return {
            "name": name,
            "description": f"A {name}.",
            "materials": ["wood"],
            "count": count,
            "mass_kg": mass,
            "length_m": None,
            "flags": list(flags),
            "capabilities": [],
        }

    return judged(
        "transform",
        effort_seconds=5400,
        transformation={
            "target_id": target,
            "tools_used": [],
            "result_state": "felled",
            "pieces": [piece("oak trunk", 1, 600.0), piece("leafy branch", 3, 15.0), piece("stump", 1, 150.0)],
        },
    )


def test_felling_a_tree_clears_its_cell_and_leaves_pieces(world):
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 33, 64)  # Oak tree_01 at (32, 64).
    assert (
        http.post(
            f"/runs/{state['run_id']}/move",
            json={"x": 32, "y": 64, "expected_version": state["event_seq"], "request_id": "into-tree"},
        ).status_code
        == 403
    )
    world.replies.append(attempt(tree_felling()))
    body = craft(http, state, "chop down the oak", "fell").json()
    state = body["state"]
    tree = state["objects"]["tree_01"]
    assert tree["condition"] == "felled" and len(tree["became"]) == 5
    pieces = [state["objects"][i] for i in tree["became"]]
    trunk, branch = pieces[0], pieces[1]
    assert trunk["capabilities"] == [] and "carry" in branch["capabilities"]
    assert {p["sprite_asset_id"] for p in pieces[1:4]} == {branch["sprite_asset_id"]}  # Identical pieces share art.
    assert len(world.painted) == 3
    assert state["sim_time_ms"] == 5_400_000
    moved = http.post(
        f"/runs/{state['run_id']}/move",
        json={"x": 32, "y": 64, "expected_version": state["event_seq"], "request_id": "through-stump"},
    )
    assert moved.status_code == 200, moved.text
    state = moved.json()["state"]
    assert http.get(f"/runs/{state['run_id']}").json() == state


def test_transform_mass_is_capped_by_the_target():
    state = fresh_state(37, 67)  # Beside the birch sapling (12 kg) at (38, 67).
    plan = judged(
        "transform",
        transformation={
            "target_id": "sapling_a",
            "tools_used": [],
            "result_state": "felled",
            "pieces": [
                {
                    "name": "birch pole",
                    "description": "A pole.",
                    "materials": ["wood", "iron"],
                    "count": 2,
                    "mass_kg": 10.0,
                    "length_m": 2.5,
                    "flags": ["light_source"],
                    "capabilities": [],
                }
            ],
        },
    )
    verdict = crafting.validate(state, plan)
    piece = verdict["transform"]["pieces"][0]
    assert piece["mass_kg"] * piece["count"] == pytest.approx(12.0)
    assert piece["materials"] == ["wood"] and piece["flags"] == []


def harm(target, result, weapon=None, area="torso"):
    return judged(
        "harm",
        harm={
            "target_id": target,
            "weapon_id": weapon,
            "result": result,
            "target_area": area,
            "outcome": "missed" if result == "missed" else "landed",
            "injury": "a deep wound" if result != "missed" else "the blow misses",
        },
    )


def beside(state, npc_id):
    npc = next(n for n in state["npcs"] if n["id"] == npc_id)
    state["player"].update(x=npc["x"], y=npc["y"] + 1)
    return npc


def armed(state):
    """An iron thing in hand: bare hands can't hurt a guard in mail (the armour law, D-41)."""
    state["objects"]["horseshoe_a"]["holder_id"] = "player"
    return "horseshoe_a"


def knife(state):
    """An iron knife in hand (D-49): deadly to the unarmoured, and to anyone's throat."""
    state["objects"]["knife_test"] = {
        "id": "knife_test",
        "name": "iron knife",
        "x": 0,
        "y": 0,
        "mass_kg": 0.3,
        "owner_id": "player",
        "holder_id": "player",
        "capabilities": ["carry"],
        "bound_to": [],
        "water_l": 0.0,
        "capacity_l": 0.0,
        "condition": "usable",
        "materials": ["iron", "wood"],
        "description": "A short iron knife.",
        "flags": ["rigid", "sharp_edge"],
        "length_m": 0.25,
        "gear": {"kind": "weapon", "class": "knife", "covers": [], "quality": "fair"},
    }
    return "knife_test"


def test_killing_a_person_is_permanent_and_they_stop_moving():
    state = fresh_state()
    bren = beside(state, "npc_bren_marr")
    blade = knife(state)  # Mail and a helmet, but nothing at the throat (D-49).
    verdict = crafting.validate(state, harm("npc_bren_marr", "killed", blade, area="neck"))
    assert verdict["category"] == "success" and "npc_oren_dast" in verdict["harm"]["witnesses"]
    commit(state, harm("npc_bren_marr", "killed", blade, area="neck"), text="cut Bren's throat")
    bren = next(n for n in state["npcs"] if n["id"] == "npc_bren_marr")
    assert not bren["alive"] and bren["health"] == 0 and bren["controller"]["activity"] == "dead"
    where = (bren["x"], bren["y"])
    later = service.npc_sim.advance_npcs(state, state["npcs"], 60_000, state["sim_time_ms"])
    assert next((n["x"], n["y"]) for n in later if n["id"] == "npc_bren_marr") == where
    again = crafting.validate(state, harm("npc_bren_marr", "killed", blade))
    assert again["category"] == "blocked" and "already dead" in again["reason"]


def test_wounds_accumulate_and_reach_is_enforced():
    state = fresh_state()
    beside(state, "npc_darin_ko")
    blade = knife(state)
    for expected_alive in (True, False):  # Unarmoured: 100 -> 30 (surprised: 70) -> dead (35)
        summary = commit(state, harm("npc_darin_ko", "wounded", blade))
        darin = next(n for n in state["npcs"] if n["id"] == "npc_darin_ko")
        darin.setdefault("mind", {})["facing_player"] = True  # He sees it coming now.
        assert darin["alive"] is expected_alive
    # The fatal wound is reported as a death, not as another wound (the bug players saw with Tomas).
    assert summary["harm"]["result"] == "killed" and "does not survive" in summary["reason"]
    assert state["last_action"]["harm"]["result"] == "killed"
    assert len(darin["injuries"]) == 2
    far = fresh_state()
    blocked = crafting.validate(far, harm("npc_mara_venn", "killed"))
    assert blocked["category"] == "blocked" and "too far" in blocked["reason"]
    assert crafting.validate(fresh_state(), harm("npc_mara_venn", "missed"))["category"] == "blocked"


# --- Several steps in one attempt ------------------------------------------------------


def stab(target, weapon, result="wounded"):
    return judged(
        "harm",
        reason=f"You stab {target} with {weapon}.",
        harm={"target_id": target, "weapon_id": weapon, "result": result, "injury": "a deep wound"},
    )


def test_make_then_use_keeps_the_new_object_and_resolves_references():
    state = fresh_state()
    beside(state, "npc_tomas_reed")
    for item in ("branch_a", "flint_a", "vine_a"):
        state["objects"][item]["holder_id"] = "player"
    summary = commit(state, spear_step(), stab("npc_tomas_reed", "made_by_step_1"), text="make a spear then stab Tomas")
    assert summary["category"] == "success" and [s["action"] for s in summary["steps"]] == ["make", "harm"]
    made = state["last_action"]["crafted"]
    assert state["objects"][made]["holder_id"] == "player"  # The spear stays in the bag.
    assert summary["harm"]["weapon_id"] == made
    assert "made_by_step_1" not in summary["reason"] and "flint-tipped spear" in summary["reason"]
    tomas = next(n for n in state["npcs"] if n["id"] == "npc_tomas_reed")
    assert tomas["health"] == 32 and not tomas.get("down")  # A crude flint spear, unexpected: 34 x 2 (D-49).


def test_a_failed_later_step_keeps_earlier_work_and_stops():
    state = fresh_state()  # Tomas is far away, so the stab cannot happen.
    for item in ("branch_a", "flint_a", "vine_a"):
        state["objects"][item]["holder_id"] = "player"
    summary = commit(state, spear_step(), stab("npc_tomas_reed", "made_by_step_1"), judged("take", take_ids=["cord_a"]))
    assert summary["category"] == "partial_success"
    assert [s["category"] for s in summary["steps"]] == ["success", "blocked"]  # The third step never ran.
    assert state["objects"][state["last_action"]["crafted"]]["holder_id"] == "player"
    assert state["objects"]["cord_a"]["holder_id"] is None
    assert "too far" in summary["reason"]


def test_a_failed_first_step_changes_nothing():
    state = fresh_state()
    before = {k: dict(v) for k, v in state["objects"].items()}
    summary = commit(state, spear_step(outcome="failed", reason="The vine snaps."), stab("npc_tomas_reed", "branch_a"))
    assert summary["category"] == "failed" and len(summary["steps"]) == 1
    assert {k: v["holder_id"] for k, v in state["objects"].items()} == {k: v["holder_id"] for k, v in before.items()}


def test_leaked_ids_are_replaced_with_names():
    state = fresh_state()
    text = consequences.humanize("You thrust branch_a at npc_tomas_reed, then drop the flint_a.", state, {})
    assert text == "You thrust the fallen branch at Tomas, then drop the flint shard."


def test_people_near_death_are_described_to_the_judge():
    state = fresh_state()
    beside(state, "npc_darin_ko")
    commit(state, harm("npc_darin_ko", "wounded", knife(state)))  # 100 -> 30, and bleeding.
    darin = next(p for p in judge_view.people_nearby(state) if p["id"] == "npc_darin_ko")
    assert darin["condition"] == "badly wounded (near death)" and len(darin["injuries"]) == 1
    assert any("cut" in c for c in darin["conditions"])  # The judge sees the bleeding cut.


# --- Acting at a distance: walking there first, or throwing ------------------------------


def test_far_items_are_reached_by_walking_first():
    state = fresh_state()  # The flint at (45, 66) is 3.6 cells away: beyond arm's reach.
    assert judge_view.walk_costs(state)["flint_a"] > 0
    summary = commit(state, judged("take", take_ids=["flint_a"]))
    assert summary["category"] == "success"
    assert state["objects"]["flint_a"]["holder_id"] == "player"
    assert cast.distance(state["player"], (45, 66)) <= tuning.REACH_CELLS
    assert state["last_action"]["walk"] and state["last_action"]["walk"][-1] == [
        state["player"]["x"],
        state["player"]["y"],
    ]


def test_melee_walks_up_to_the_target():
    state = fresh_state()
    bren = beside(state, "npc_bren_marr")
    state["player"].update(x=bren["x"], y=bren["y"] + 5)
    summary = commit(state, harm("npc_bren_marr", "wounded", armed(state)))
    assert summary["category"] == "success"
    assert cast.distance(state["player"], bren) <= tuning.REACH_CELLS
    assert next(n for n in state["npcs"] if n["id"] == "npc_bren_marr")["health"] < 100


def throw(target, weapon, result="wounded"):
    return judged(
        "harm",
        harm={"target_id": target, "weapon_id": weapon, "method": "thrown", "result": result, "injury": "a hard blow"},
    )


def test_a_thrown_weapon_lands_by_the_target_and_the_thrower_stays_put():
    state = fresh_state()
    bren = beside(state, "npc_bren_marr")
    state["player"].update(x=bren["x"], y=bren["y"] + 5)
    state["objects"]["stone_a"]["holder_id"] = "player"
    here = (state["player"]["x"], state["player"]["y"])
    summary = commit(state, throw("npc_bren_marr", "stone_a"))
    assert summary["category"] == "success" and summary["harm"]["method"] == "thrown"
    assert (state["player"]["x"], state["player"]["y"]) == here
    stone = state["objects"]["stone_a"]
    assert stone["holder_id"] is None and cast.distance(stone, bren) <= 3


def test_throws_need_a_held_light_item_within_range():
    state = fresh_state()
    bren = beside(state, "npc_bren_marr")
    state["player"].update(x=bren["x"], y=bren["y"] + 5)
    not_held = crafting.validate(state, throw("npc_bren_marr", "stone_a"))
    assert not_held["category"] in ("blocked", "unresolved")
    state["objects"]["stone_a"]["holder_id"] = "player"
    state["player"].update(x=bren["x"], y=bren["y"] + 12)
    far = crafting.validate(state, throw("npc_bren_marr", "stone_a"))
    assert far["category"] == "blocked" and "too far" in far["reason"]


def test_a_later_step_can_show_light_or_give_what_an_earlier_step_made():
    """'Make a sling, then show Kade': every later step may name made_by_step_N, not only weapons and ingredients."""
    state = fresh_state()
    beside(state, "npc_tomas_reed")
    for item in ("branch_a", "flint_a", "vine_a"):
        state["objects"][item]["holder_id"] = "player"
    shown = judged(
        "demonstrate",
        demonstration={
            "object_id": "made_by_step_1",
            "used_ids": [],
            "audience_ids": ["npc_tomas_reed"],
            "observed": "The stranger jabbed the spear into a post.",
            "works": True,
            "capabilities": [],
            "wonder": "ordinary",
        },
    )
    given = judged("give", give={"item_ids": ["made_by_step_1"], "recipient_id": "npc_tomas_reed"})
    summary = commit(state, spear_step(), shown, given, text="make a spear, show Tomas, then give it to him")
    assert [s["category"] for s in summary["steps"]] == ["success", "success", "success"], summary["steps"]
    assert state["objects"][state["last_action"]["crafted"]]["holder_id"] == "npc_tomas_reed"


def gather_step(source="tree_01", name="oak leaf", materials=("leaf",), count=1, mass=0.01):
    return {
        "action": "gather",
        "outcome": "success",
        "reason": "You pull a leaf off the oak.",
        "effort_seconds": 3,
        "new_object": None,
        "take_ids": [],
        "transformation": None,
        "harm": None,
        "gather": {
            "source_id": source,
            "tools_used": [],
            "piece": {
                "name": name,
                "description": "A broad green oak leaf.",
                "materials": list(materials),
                "count": count,
                "mass_kg": mass,
                "length_m": None,
                "flags": ["flexible"],
                "capabilities": [{"text": "can float on water", "status": "expected"}],
            },
        },
    }


def test_a_leaf_can_be_taken_off_a_tree_and_the_tree_stays(world):
    """D-48: a part of something larger (a leaf, a twig, a handful), with the source left where it is."""
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 33, 64)  # Oak tree_01 at (32, 64).
    world.replies.append(attempt(gather_step(), key="gather:leaf|tree"))
    body = craft(http, state, "pull a leaf off the tree", "leaf").json()
    state = body["state"]
    leaf = state["objects"][f"gathered_{state['event_seq']}_1"]
    assert leaf["name"] == "oak leaf" and leaf["materials"] == ["leaf"] and leaf["holder_id"] == "player"
    assert leaf["owner_id"] == "player" and leaf["components"] == ["tree_01"]
    tree = state["objects"]["tree_01"]
    assert tree["condition"] == "usable" and tree["holder_id"] is None  # Still standing, still in the way.
    assert http.get(f"/runs/{state['run_id']}").json() == state  # Replays exactly.


def test_gathering_keeps_to_the_source_and_to_a_handful(world):
    http = world.http
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 33, 64)
    world.replies.append(attempt(gather_step(name="iron leaf", materials=("iron",), count=3, mass=2.0)))
    state = craft(http, state, "pull some iron leaves off the tree", "iron").json()["state"]
    made = [o for o in state["objects"].values() if o["id"].startswith("gathered_")]
    assert len(made) == 3 and all(o["materials"] == ["wood"] for o in made)  # Iron doesn't grow on oaks.
    assert sum(o["mass_kg"] for o in made) <= tuning.GATHER_MAX_KG + 0.01
