"""D-64: failures observed in the two player journeys on 4 October, with no paid model calls."""

import copy

import pytest
from test_craft import attempt, commit, judged, spear_step
from test_encounter import post, world  # noqa: F401
from test_gate import answers
from test_talk import npc, unit_state

import attempts
import cast
import clock
import consequences
import crafting
import judge_view
import patch
import persona
import store
import talk
from ai import config, judge, voice


def held_materials():
    state = unit_state()
    for item_id in ("branch_a", "flint_a", "vine_a"):
        state["objects"][item_id]["holder_id"] = "player"
    return state


def test_redundant_pickup_does_not_stop_assembly_or_spend_time():
    state = held_materials()
    payload, result, draft = consequences.resolve_attempt(
        state,
        state["run_id"],
        "take my materials and assemble them",
        attempt(judged("take", take_ids=["branch_a", "flint_a", "vine_a"]), spear_step()),
        None,
        "retry",
        0,
    )
    assert result["category"] == "success"
    assert result["effort_seconds"] == 40
    assert result["take_ids"] == []
    assert payload["journal_entry"]["made"] in draft["objects"]


def test_retry_reports_the_actual_blocker_without_phantom_partial_success():
    state = held_materials()
    blocked = judged("make", outcome="blocked", reason="You cannot cut the iron chain with these tools.")
    blocked["effort_seconds"] = 0
    _, result, draft = consequences.resolve_attempt(
        state,
        state["run_id"],
        "shorten and attach the chain",
        attempt(judged("take", take_ids=["branch_a"]), blocked),
        None,
        "retry",
        0,
    )
    assert result["category"] == "blocked"
    assert result["reason"] == blocked["reason"]
    assert result["effort_seconds"] == 0
    assert draft["sim_time_ms"] == state["sim_time_ms"]
    assert draft["objects"] == state["objects"]


def test_skipped_prerequisite_keeps_later_step_references_correct():
    state = held_materials()
    payload, result, draft = consequences.resolve_attempt(
        state,
        state["run_id"],
        "make it and hold it",
        attempt(
            judged("take", take_ids=["branch_a"]),
            spear_step(),
            judged("equip", equip={"object_id": "made_by_step_2", "slot": "right", "put_on": True}),
        ),
        None,
        "reference",
        0,
    )
    assert result["category"] == "success"
    assert draft["player"]["equipped"]["right"] == payload["journal_entry"]["made"]


def test_excess_redundant_steps_do_not_crash_or_execute_beyond_the_step_limit():
    state = held_materials()
    _, result, draft = consequences.resolve_attempt(
        state,
        state["run_id"],
        "a malformed long pickup plan",
        attempt(*[judged("take", take_ids=["branch_a"]) for _ in range(consequences.MAX_STEPS)], spear_step()),
        None,
        "too-many",
        0,
    )
    assert result["effort_seconds"] == 0
    assert draft["objects"] == state["objects"]


def test_existing_binding_is_part_of_the_new_assembly_not_an_invisible_blocker():
    state = held_materials()
    state["objects"]["branch_a"]["bound_to"] = ["vine_a"]
    # Omission of an existing binding is the defect in the saved plated-mace proposal.
    plan = spear_step(consumes=["branch_a", "flint_a"], materials=["wood", "flint"], mass_kg=1.5)
    original = copy.deepcopy(plan)
    commit(state, plan)
    made = state["objects"][state["last_action"]["made"]]
    assert made["components"] == ["branch_a", "flint_a", "vine_a"]
    assert made["mass_kg"] == pytest.approx(1.5 + state["objects"]["vine_a"]["mass_kg"])
    assert "vine" in made["materials"]
    assert "vine" in made["description"]
    assert state["objects"]["vine_a"]["holder_id"] == f"in:{made['id']}"
    assert plan == original  # Revalidation cannot add the binding's mass twice.


def test_connected_parts_are_transitive_and_include_old_one_sided_links():
    state = held_materials()
    state["objects"]["vine_a"]["bound_to"] = ["branch_a", "flint_a"]
    assert crafting.connected_items(state, ["branch_a"]) == ["branch_a", "vine_a", "flint_a"]


@pytest.mark.parametrize("fixed", [True, False])
def test_assembly_cannot_absorb_a_fixed_or_unavailable_attachment(fixed):
    state = held_materials()
    state["objects"]["branch_a"]["bound_to"] = ["vine_a"]
    vine = state["objects"]["vine_a"]
    if fixed:
        vine["capabilities"] = []
    else:
        vine["holder_id"] = "npc_hessa_marr"
    result = crafting.validate(state, spear_step(consumes=["branch_a", "flint_a"], mass_kg=1.8))
    assert result["category"] == "blocked"
    assert not result["consumed_ids"]


def test_wrong_distance_block_gets_one_bounded_review_using_the_same_world(monkeypatch):
    state = unit_state()
    branch = state["objects"]["branch_a"]
    state["player"].update(x=branch["x"] + 8, y=branch["y"])
    context = judge_view.build_context(state, "carve a grip in the wood", [])
    blocked = judged("physical", outcome="blocked", reason="The wood is several steps away.", resource_ids=["branch_a"])
    success = judged("physical", resource_ids=["branch_a"])
    calls = []

    def propose(view):
        calls.append(view)
        return judge.JudgeCall(status="ok", result=attempt(blocked if len(calls) == 1 else success), attempts=1)

    monkeypatch.setattr(judge, "judge_craft", propose)
    result = attempts.judge_attempt(context, 0)
    assert result.result["steps"][0]["outcome"] == "success"
    assert result.attempts == 2
    assert len(calls) == 2
    assert calls[1]["available_items"] == calls[0]["available_items"]
    assert calls[1]["proposal_to_check"]["steps"][0]["reason"] == blocked["reason"]


def test_review_can_confirm_a_real_physical_limit_and_respects_call_allowance(monkeypatch):
    context = {"available_items": [{"id": "wood", "walk_steps": 12}]}
    blocked = attempt(judged("physical", outcome="blocked", reason="No suitable cutting tool.", resource_ids=["wood"]))
    calls = []

    def propose(view):
        calls.append(view)
        return judge.JudgeCall(status="ok", result=copy.deepcopy(blocked), attempts=1)

    monkeypatch.setattr(judge, "judge_craft", propose)
    result = attempts.judge_attempt(context, 0)
    assert len(calls) == 2 and result.result == blocked
    calls.clear()
    monkeypatch.setattr(config, "max_calls_per_run", lambda: 1)
    result = attempts.judge_attempt(context, 0)
    assert len(calls) == 1 and result.result == blocked


def test_vouch_carries_the_request_only_to_its_actual_recipient_on_arrival():
    state = unit_state()
    hessa, captain = npc(state, "npc_hessa_marr"), cast.captain(state)
    message = "The stranger brought my kitchen water and asked me to speak for them to enter the city."
    persona.knows(hessa)["notes"].append("I have a private worry that is not part of this recommendation.")
    talk.exchange(
        state,
        hessa["id"],
        "Here's the water.",
        answers("vouch"),
        "vouch",
        "I'll speak for you.",
        [],
        errand_message=message,
    )
    assert not persona.knows(captain).get("heard")
    assert not state.get("admitted")
    for _ in range(160):
        state["npcs"], _, state["player"] = clock.advance_world(state, 1000, state["sim_time_ms"])
        state["sim_time_ms"] += 1000
        if persona.knows(cast.captain(state)).get("heard"):
            break
    captain = cast.captain(state)
    assert persona.knows(captain)["heard"][-1]["text"] == message
    assert any(p["npc_id"] == captain["id"] and p["kind"] == "decide" for p in state["pending_minds"])
    assert "private worry" not in str(persona.knows(captain))
    assert not state.get("admitted")  # Delivery is evidence, never an automatic quest unlock.


def test_fulfilled_deal_keeps_its_specific_reason_when_the_move_is_vouch():
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    talk.propose(state, hessa, "water_haul", 1, "Bring kitchen water.", [], [])
    deal = next(iter(state["agreements"].values()))
    deal["status"] = "accepted"
    state["objects"]["bucket_hessa"].update(holder_id=hessa["id"], water_l=10.0)
    talk.exchange(state, hessa["id"], "Here's your water.", answers("vouch", done=0.9), "vouch", "Thank you.", [])
    assert deal["status"] == "fulfilled"
    assert deal["task"] in hessa["mind"]["job"]["summary"]


@pytest.mark.parametrize(
    "move,reason,threat,admitted",
    [("admit", 0.9, 0.1, True), ("carry_on", 0.9, 0.1, False), ("admit", 0.1, 0.9, False)],
)
def test_recipient_can_decide_entry_from_the_handoff_without_another_player_message(
    world, monkeypatch, move, reason, threat, admitted
):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    with store.db() as connection:
        _, saved = store.load_run(connection, state["run_id"])
        before = patch.snapshot(saved)
        saved["pending_minds"] = []
        captain, hessa = cast.captain(saved), npc(saved, "npc_hessa_marr")
        saved["player"].update(x=captain["x"], y=captain["y"] + 1)
        hessa.update(x=captain["x"] + 1, y=captain["y"])
        clock._deliver_vouch(
            saved,
            hessa,
            captain,
            0,
            saved["journal"],
            {
                "why": "They helped me.",
                "summary": "Hessa recommends the stranger.",
                "event": 1,
                "message": "They brought my water and asked to enter the city. I speak for them.",
            },
        )
        store.record(connection, before, saved, "setup", "handoff", 0)
    seen = []

    def react(context):
        seen.append(context)
        return voice.VoiceCall(status="ok", text="", model="script"), {
            "move": move,
            "answers": answers(move, reason=reason, threat=threat),
            "text": "I have heard Hessa's recommendation.",
            "remember": "Hessa vouched for entry.",
            "intents": [],
            "defend_if_attacked": True,
        }

    monkeypatch.setattr(config, "mode", lambda: "live")
    monkeypatch.setattr(voice, "react", react)
    state = world.http.get(f"/runs/{state['run_id']}").json()
    body = post(world, state, "think", {})
    after = body["state"]
    assert len(seen) == 1
    assert seen[0]["can_let_the_stranger_through"]
    assert seen[0]["who_they_would_let_through"]
    assert "asked to enter" in str(seen[0]["evidence"])
    assert seen[0]["incoming_recommendation"]["from_name"] == "Hessa"
    assert bool(after.get("admitted")) == admitted
    assert bool(after.get("gate_open")) == admitted
    assert world.http.get(f"/runs/{state['run_id']}").json() == after
