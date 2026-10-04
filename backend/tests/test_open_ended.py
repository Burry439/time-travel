"""D-62: regression tests for causal facts, personal knowledge and an open-ended reducer."""

import copy

import pytest
from test_craft import attempt, commit, judged, spear_step
from test_encounter import world  # noqa: F401
from test_reputation import shown, watching
from test_talk import npc, unit_state

import actors
import agreements
import cast
import combat
import consequences
import crafting
import evidence
import paths
import reputation
import stories
import talk


def test_paraphrased_proof_cannot_renew_goodwill_after_memories_are_pruned():
    state = watching("npc_roderic_vale")
    guard = npc(state, "npc_roderic_vale")
    import perception

    perception.apply_perceptions(state, perception.perceive(state, shown("ordinary")))
    for _ in range(30):
        talk.update_regard(guard, {"impression": {"score": 4}, "suspicion": {"score": 0}})
    before = dict(reputation.regard(guard))
    guard["mind"]["memories"].clear()
    for event in range(10, 30):
        proof = shown("clever")
        proof["event_id"] = event
        proof["demonstration"]["observed"] = f"A differently worded explanation, number {event}."
        perception.apply_perceptions(state, perception.perceive(state, proof))
        talk.update_regard(guard, {"impression": {"score": 4}, "suspicion": {"score": 0}})
    assert reputation.regard(guard) == before
    assert len(evidence.held(guard)) == 1


def test_absent_person_does_not_learn_that_a_confidence_was_betrayed():
    state = unit_state()
    state.setdefault("learned", []).append({"secret": "tomas_cracked"})
    captain, tomas = npc(state, "npc_roderic_vale"), npc(state, "npc_tomas_reed")
    state["player"].update(x=40, y=40)
    captain.update(x=41, y=40)
    tomas.update(x=10, y=65)
    before = copy.deepcopy(tomas)
    stories.tell(state, ["tomas_cracked"], [captain], 8, 100)
    stories.tick(state)
    assert tomas == before
    assert not stories.how_things_stand(state, tomas)
    assert any(m["kind"] == "disclosure" for m in evidence.held(captain))


def test_both_victims_remember_separate_impacts_in_one_attempt():
    state = watching("npc_hessa_marr", "npc_tomas_reed")
    steps = [
        judged(
            "harm",
            harm={
                "target_id": target,
                "weapon_id": None,
                "method": "melee",
                "family": "other",
                "result": "wounded",
                "injury": "a scratch",
                "outcome": "landed",
                "target_area": "arm",
                "held_seconds": 0,
            },
        )
        for target in ("npc_hessa_marr", "npc_tomas_reed")
    ]
    commit(state, *steps)
    for target in ("npc_hessa_marr", "npc_tomas_reed"):
        assert any(m["kind"] == "violence" and m["victim"] == target for m in evidence.held(npc(state, target)))
    assert len(state["incidents"]) >= 2


def test_named_remote_audience_cannot_witness_a_demonstration():
    import perception

    state = watching("npc_hessa_marr")
    remote = npc(state, "npc_roderic_vale")
    remote.update(x=10, y=65)
    proof = shown("uncanny")
    proof["demonstration"]["audience_ids"] = [remote["id"]]
    observed = perception.perceive(state, proof)
    assert remote["id"] not in {p["npc_id"] for p in observed}


def test_returning_a_copy_to_someone_else_does_not_settle_the_original_theft():
    state = watching("npc_tomas_reed", "npc_hessa_marr")
    rope = state["objects"]["rope_tomas"]
    rope.update(x=40, y=40, holder_id=None)
    commit(state, judged("take", take_ids=["rope_tomas"]))
    state["event_seq"] += 1
    tomas = npc(state, "npc_tomas_reed")
    assert reputation.unresolved_crime(tomas) is not None
    state["objects"]["copy"] = {**copy.deepcopy(rope), "id": "copy", "owner_id": "player", "holder_id": "player"}
    commit(state, judged("give", give={"item_ids": ["copy"], "recipient_id": "npc_hessa_marr"}))
    assert reputation.unresolved_crime(tomas) is not None
    state["event_seq"] += 1
    commit(state, judged("give", give={"item_ids": ["rope_tomas"], "recipient_id": tomas["id"]}))
    assert reputation.unresolved_crime(npc(state, tomas["id"])) is None


def test_non_ferromagnetic_material_cannot_be_made_magnetic_by_a_lodestone():
    state = unit_state()
    state["objects"]["iron_bar"] = {
        **state["objects"]["branch_a"],
        "id": "iron_bar",
        "materials": ["bronze"],
        "holder_id": "player",
        "mass_kg": 0.1,
    }
    state["objects"]["lodestone_darin"]["holder_id"] = "player"
    step = spear_step(
        consumes=["iron_bar"], tools_used=["lodestone_darin"], materials=["bronze"], mass_kg=0.1, flags=["magnetized"]
    )
    result = crafting.validate(state, step)
    assert result["category"] == "unresolved"
    assert "non-ferromagnetic" in " ".join(result["notes"])


def test_novel_physical_property_persists_and_is_available_for_a_second_use():
    state = unit_state()
    state["objects"]["branch_a"]["holder_id"] = "player"
    attribute = {
        "name": "graduated_helical_channel",
        "value": "A shallow spiral carved for metering seeds",
        "status": "expected",
        "basis_ids": ["branch_a"],
    }
    commit(
        state,
        judged(
            "physical",
            resource_ids=["branch_a"],
            effects=[{"kind": "attribute", "target_id": "branch_a", "other_id": None, "attribute": attribute}],
        ),
    )
    import judge_view

    view = judge_view.build_context(state, "Use the spiral to meter seeds into rows", [])
    branch = next(o for o in view["available_items"] if o["id"] == "branch_a")
    assert branch["attributes"] == [attribute]
    assert state["precedents"][-1]["inputs"]["branch_a"].get("attributes", []) == []
    forbidden = copy.deepcopy(attribute)
    forbidden["name"] = "admitted"
    commit(
        state,
        judged(
            "physical",
            resource_ids=["branch_a"],
            effects=[{"kind": "attribute", "target_id": "branch_a", "other_id": None, "attribute": forbidden}],
        ),
    )
    assert not state.get("admitted")
    assert state["last_action"]["category"] == "unresolved"


def test_dynamic_agreement_rewards_once_and_requires_real_owned_resources():
    state = watching("npc_hessa_marr")
    hessa = npc(state, "npc_hessa_marr")
    bowl = state["objects"]["bowl_hessa"]
    bowl.update(holder_id=hessa["id"])
    reward = {"kind": "give", "object_ids": [bowl["id"]], "goal": [], "task": "payment"}
    valid, key = agreements.apply(
        state,
        hessa,
        {
            "action": "offer",
            "task": "Invent a seed dispenser",
            "check": "Show me evenly spaced seeds",
            "rewards": [reward],
        },
        1,
    )
    assert valid
    assert agreements.apply(state, hessa, {"action": "accept", "agreement_id": key}, 2)[0]
    # She can believe a claim; it does not certify physical success.
    assert agreements.apply(state, hessa, {"action": "satisfied", "agreement_id": key, "evidence_ids": []}, 3)[0]
    assert bowl["holder_id"] == "player" and bowl["owner_id"] == "player"
    assert state["agreements"][key]["objective_evidence_ids"] == []
    assert not agreements.apply(state, hessa, {"action": "satisfied", "agreement_id": key}, 4)[0]
    reward["object_ids"] = ["rope_tomas"]
    assert not agreements.apply(state, hessa, {"action": "offer", "task": "Another invention", "rewards": [reward]}, 5)[
        0
    ]


def test_a_helper_needs_an_actual_commitment_not_just_high_trust():
    state = watching("npc_tomas_reed")
    tomas = npc(state, "npc_tomas_reed")
    reputation.regard(tomas)["trust"] = 1
    assert not reputation.will_help(state, tomas)
    agreements.execute(state, tomas, {"kind": "help", "task": "lift a log", "object_ids": [], "goal": []}, 2)
    assert reputation.will_help(state, tomas)
    tomas["down"] = True
    assert not reputation.will_help(state, tomas)


def test_npc_physical_work_uses_the_same_reducer_and_keeps_player_inventory():
    state = watching("npc_tomas_reed")
    tomas = npc(state, "npc_tomas_reed")
    for oid in ("branch_a", "flint_a", "vine_a"):
        state["objects"][oid].update(holder_id=tomas["id"], owner_id=tomas["id"])
    cast.mind(tomas)["physical_intention"] = "Lash my flint to my branch with my vine"
    original_player = copy.deepcopy(state["player"])
    verdict = actors.perform(state, tomas["id"], attempt(spear_step()))
    assert verdict["category"] == "success"
    made = state["objects"][state["last_action"]["made"]]
    assert made["holder_id"] == tomas["id"] and made["owner_id"] == tomas["id"]
    assert state["player"]["x"] == original_player["x"] and state["player"]["y"] == original_player["y"]
    assert made["created_by"] == tomas["id"]


def test_combat_partition_does_not_erase_an_earlier_npc_impact():
    state = watching("npc_bren_marr")
    guard = npc(state, "npc_bren_marr")
    state["player"].update(x=40, y=40)
    guard.update(x=41, y=40, health=1)
    combat.start(state, [guard["id"]], 0, "test", lethal=True)
    assert combat.strike(state, "right", guard["id"], 0)["ok"]
    state["player"]["swings"]["right"]["lands_at"] = 200
    profile = combat.npc_weapon(state, guard)
    state["fight"]["swings"][guard["id"]] = {"lands_at": 100, "started": 0, "profile": profile}
    together, split = copy.deepcopy(state), copy.deepcopy(state)
    combat.tick(together, together["npcs"], 300, 0, paths.grid(together), [])
    combat.tick(split, split["npcs"], 100, 0, paths.grid(split), [])
    combat.tick(split, split["npcs"], 200, 100, paths.grid(split), [])
    assert together["player"]["health"] < 100
    assert together["player"]["health"] == pytest.approx(split["player"]["health"])


def test_a_started_attack_cannot_substitute_a_new_weapon():
    state = watching("npc_hessa_marr")
    state["objects"]["flint_a"]["holder_id"] = "player"
    state["player"]["equipped"] = {"right": "flint_a"}
    assert combat.strike(state, "right", "npc_hessa_marr", 0)["ok"]
    state["player"]["equipped"].clear()
    combat.tick(state, state["npcs"], 1000, 0, paths.grid(state), [])
    assert npc(state, "npc_hessa_marr").get("health", 100) == 100


def test_a_later_failure_keeps_earlier_completed_work():
    state = unit_state()
    state["objects"]["branch_a"]["holder_id"] = "player"
    payload, verdict, _ = consequences.resolve_attempt(
        state,
        state["run_id"],
        "take then use a missing tool",
        attempt(judged("take", take_ids=["flint_a"]), judged("take", take_ids=["nonexistent"])),
        None,
        "partial",
        0,
    )
    consequences.apply_payload(state, payload)
    assert verdict["category"] == "partial_success"
    assert state["objects"]["flint_a"]["holder_id"] == "player"


def test_news_preserves_the_original_proof_identity():
    import perception
    import village

    state = watching("npc_hessa_marr")
    hessa, bren = npc(state, "npc_hessa_marr"), npc(state, "npc_bren_marr")
    perception.apply_perceptions(state, perception.perceive(state, shown("clever")))
    memory = evidence.held(hessa)[0]
    village._pass_on(state, hessa, bren, {"kind": "news", "memory": memory}, True, 10000)
    assert evidence.held(bren)[-1]["evidence_id"] == memory["evidence_id"]
    count = len(evidence.held(hessa))
    village._pass_on(state, bren, hessa, {"kind": "news", "memory": evidence.held(bren)[-1]}, True, 20000)
    assert len(evidence.held(hessa)) == count


def test_an_identical_attribute_effect_does_not_mint_a_new_revision():
    state = unit_state()
    state["objects"]["branch_a"]["holder_id"] = "player"
    effect = {
        "kind": "attribute",
        "target_id": "branch_a",
        "other_id": None,
        "attribute": {"name": "groove", "value": "shallow channel", "status": "expected", "basis_ids": ["branch_a"]},
    }
    proposal = judged("physical", resource_ids=["branch_a"], effects=[effect])
    commit(state, proposal)
    first = state["objects"]["branch_a"]["revision"]
    state["event_seq"] += 1
    commit(state, proposal)
    assert state["objects"]["branch_a"]["revision"] == first


def test_equivalent_causal_failure_gets_only_one_reconsideration(monkeypatch):
    import attempts
    import judge_view
    from ai import judge

    state = unit_state()
    state["objects"]["branch_a"]["holder_id"] = "player"
    failed = judged("physical", resource_ids=["branch_a"])
    failed.update(outcome="failed", reason="The available material cannot support that force.")
    commit(state, failed)
    context = judge_view.build_context(state, "Try the identical mechanism again", [])
    key = state["precedents"][-1]["key"]
    success = attempt(judged("physical", resource_ids=["branch_a"]), key=key)
    calls = []

    def answer(view):
        calls.append(view)
        return judge.JudgeCall(status="ok", result=copy.deepcopy(success), attempts=1)

    monkeypatch.setattr(judge, "judge_craft", answer)
    result = attempts.judge_attempt(context, 0)
    assert len(calls) == 2 and "contradictory_precedent" in calls[1]
    assert result.status == "error" and result.result is None


def test_a_pending_intention_revalidates_after_movement(world, monkeypatch):
    import app as service

    state = world.http.post("/runs", json={"mode": "developer"}).json()

    def answer(context):
        moved = world.http.post(
            f"/runs/{state['run_id']}/move",
            json={"cells": [[49, 68]], "expected_version": state["event_seq"], "request_id": "during-model"},
        )
        assert moved.status_code == 200
        return service.judge.JudgeCall(status="ok", result=attempt(judged("other")), attempts=1)

    monkeypatch.setattr(service.judge, "judge_craft", answer)
    reply = world.http.post(
        f"/runs/{state['run_id']}/craft",
        json={
            "text": "Inspect what I am holding",
            "selected_ids": [],
            "expected_version": state["event_seq"],
            "request_id": "pending",
        },
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["state"]["player"]["x"] == 49
    repeat = world.http.post(
        f"/runs/{state['run_id']}/craft",
        json={
            "text": "Inspect what I am holding",
            "selected_ids": [],
            "expected_version": state["event_seq"],
            "request_id": "pending",
        },
    )
    assert repeat.json()["duplicate"] and repeat.json()["state"] == reply.json()["state"]


def test_a_pending_intention_cannot_resurrect_a_dead_player(world, monkeypatch):
    import app as service
    import commands

    state = world.http.post("/runs", json={"mode": "developer"}).json()

    def answer(context):
        with commands.open(state["run_id"], playable=False, stale=False) as command:
            command.state["player"].update(alive=False, health=0)
            command.save("test-death", command.state["tick"])
        return service.judge.JudgeCall(status="ok", result=attempt(judged("other")), attempts=1)

    monkeypatch.setattr(service.judge, "judge_craft", answer)
    reply = world.http.post(
        f"/runs/{state['run_id']}/craft",
        json={
            "text": "Inspect my belongings",
            "selected_ids": [],
            "expected_version": state["event_seq"],
            "request_id": "dead-pending",
        },
    )
    assert reply.status_code == 409
    loaded = world.http.get(f"/runs/{state['run_id']}").json()
    assert not loaded["player"]["alive"] and loaded["last_action"] is None


def test_transform_preserves_novel_properties_without_claiming_a_test():
    state = unit_state()
    for oid in ("branch_a", "flint_a"):
        state["objects"][oid]["holder_id"] = "player"
    proposal = judged(
        "transform",
        transformation={
            "target_id": "branch_a",
            "tools_used": ["flint_a"],
            "result_state": "cut_up",
            "pieces": [
                {
                    "name": "channel stick",
                    "description": "A carved water channel.",
                    "materials": ["wood"],
                    "count": 1,
                    "mass_kg": 0.1,
                    "length_m": 0.2,
                    "flags": ["rigid"],
                    "capabilities": [],
                    "attributes": [
                        {
                            "name": "channel",
                            "value": "spiral groove",
                            "status": "observed",
                            "basis_ids": ["branch_a", "flint_a"],
                        }
                    ],
                }
            ],
        },
    )
    commit(state, proposal)
    obj = next(o for o in state["objects"].values() if o["name"] == "channel stick")
    assert obj["attributes"][0]["value"] == "spiral groove"
    assert obj["attributes"][0]["status"] == "expected"
    import judge_view

    assert (
        next(
            o for o in judge_view.build_context(state, "Use the channel", [])["available_items"] if o["id"] == obj["id"]
        )["attributes"]
        == obj["attributes"]
    )


def test_same_helper_can_change_a_ruling_after_accepting_the_work():
    import judge_view
    import precedents

    state = watching("npc_hessa_marr")
    state["objects"]["branch_a"]["holder_id"] = "player"
    failed = judged("physical", resource_ids=["branch_a"], helper_ids=["npc_hessa_marr"])
    failed.update(outcome="blocked", reason="The helper has not agreed.")
    commit(state, failed)
    helper = npc(state, "npc_hessa_marr")
    cast.mind(helper).setdefault("commitments", []).append(
        {"kind": "help", "status": "accepted", "task": "hold the branch", "until": state["sim_time_ms"] + 60000}
    )
    result = attempt(
        judged("physical", resource_ids=["branch_a"], helper_ids=[helper["id"]]), key=state["precedents"][-1]["key"]
    )
    assert precedents.contradiction(judge_view.build_context(state, "Help me now", []), result) is None


def test_restitution_reaches_a_remote_witness_only_through_believed_news():
    import village

    state = watching("npc_hessa_marr", "npc_tomas_reed")
    hessa, tomas = npc(state, "npc_hessa_marr"), npc(state, "npc_tomas_reed")
    memory = {
        "kind": "theft",
        "severity": 2,
        "clarity": "clear",
        "summary": "The stranger stole the rope.",
        "short": "stole the rope",
        "event": 1,
        "at": 0,
        "victim": tomas["id"],
        "object_id": "rope_tomas",
        "item": "rope",
        "actor_id": "player",
    }
    reputation.remember(hessa, copy.deepcopy(memory))
    reputation.remember(tomas, copy.deepcopy(memory))
    reputation.settle(state, "given back", object_id="rope_tomas", npc_ids={tomas["id"]})
    assert reputation.unresolved_crime(hessa) is not None
    topic = next(v for v in village.topics(state, tomas, hessa).values() if v["kind"] == "news")
    village._pass_on(state, tomas, hessa, topic, False, 10)
    assert reputation.unresolved_crime(hessa) is not None
    village._pass_on(state, tomas, hessa, topic, True, 20)
    assert reputation.unresolved_crime(hessa) is None
    assert len(evidence.held(hessa)) == 1


def test_conversation_shares_one_deadline_across_its_model_calls(world, monkeypatch):
    import time

    from test_talk import said

    import app as service
    import commands

    state = world.http.post("/runs", json={"mode": "developer"}).json()
    with commands.open(state["run_id"], playable=False, stale=False) as cmd:
        hessa = npc(cmd.state, "npc_hessa_marr")
        cmd.state["player"].update(x=hessa["x"], y=hessa["y"] + 1)
        cmd.save("test-position", cmd.state["tick"])
        state = cmd.state
    original = service.voice.scene
    budgets = []

    def answer(*args, **kwargs):
        end = service.ai_config.deadline.get()
        assert end is not None
        budgets.append(end - time.monotonic())
        return original(*args, **kwargs)

    monkeypatch.setattr(service.voice, "scene", answer)
    world.replies.append(said("answer"))
    reply = world.http.post(
        f"/runs/{state['run_id']}/say",
        json={
            "npc_id": "npc_hessa_marr",
            "text": "Good day.",
            "expected_version": state["event_seq"],
            "request_id": "shared-deadline",
        },
    )
    assert reply.status_code == 200, reply.text
    assert budgets and all(0 < b <= service.ai_config.SPEECH_BUDGET_S for b in budgets)


def test_a_redundant_authored_reward_acknowledgment_does_not_deny_or_pay_twice():
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    state["agreements"] = {"example": {"id": "example", "issuer": hessa["id"], "status": "fulfilled"}}
    before = copy.deepcopy(state)
    valid, _ = agreements.apply(
        state,
        hessa,
        {"action": "satisfied", "agreement_id": "example", "rewards": [{"kind": "give", "object_ids": ["bowl_hessa"]}]},
        20,
    )
    assert valid and state == before
