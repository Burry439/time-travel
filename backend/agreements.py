"""Negotiated commitments. NPC satisfaction and physical truth are separate records."""

from __future__ import annotations

import cast
import gatekeeping
import paths
import reputation
import tuning


def apply(state: dict, npc: dict, proposal: dict, event: int) -> tuple[bool, str]:
    if not npc.get("alive", True) or npc.get("down"):
        return False, "They cannot act now."
    action = proposal.get("action")
    deals = state.setdefault("agreements", {})
    if action == "offer":
        task = proposal.get("task", "").strip()[:400]
        rewards = proposal.get("rewards", [])
        if not task or not rewards or any(not authorized(state, npc, r, future=True) for r in rewards):
            return False, "The proposed deal promises unavailable resources or authority."
        key = f"negotiated_{npc['id']}_{event}"
        deals.setdefault(
            key,
            {
                "id": key,
                "type": "negotiated",
                "issuer": npc["id"],
                "task": task,
                "check": proposal.get("check", "")[:400],
                "reward": "negotiated",
                "rewards": rewards,
                "status": "proposed",
                "offered_event": event,
                "evidence_ids": [],
                "objective_evidence_ids": [],
            },
        )
        return True, key
    deal = deals.get(proposal.get("agreement_id"))
    if not deal or deal.get("issuer") != npc["id"]:
        return False, "This person did not offer that agreement."
    if deal.get("type") != "negotiated":
        # The conversation reading already processes authored example deals. A redundant
        # acknowledgment from the same model must not deny or execute that reward twice.
        if (action == "accept" and deal["status"] in ("accepted", "fulfilled")) or (
            action == "satisfied" and deal["status"] == "fulfilled"
        ):
            return True, deal["id"]
        return False, "That example agreement is decided by the conversation reading."
    if action == "accept" and deal["status"] == "proposed":
        deal.update(status="accepted", accepted_event=event)
        return True, deal["id"]
    if action == "satisfied" and deal["status"] == "accepted":
        known = (npc.get("mind") or {}).get("evidence", {})
        cited = proposal.get("evidence_ids", [])
        if any(i not in known for i in cited):
            return False, "They cannot cite evidence they never received."
        # Claims can deceive a person; that decision does not certify a physical success.
        if any(not authorized(state, npc, r) for r in deal["rewards"]):
            return False, "The promised reward is no longer available."
        for reward in deal["rewards"]:
            execute(state, npc, reward, event)
        deal.update(
            status="fulfilled",
            fulfilled_event=event,
            evidence_ids=cited,
            objective_evidence_ids=[
                i for i in cited if known[i].get("source") in reputation.FIRSTHAND and known[i].get("works", False)
            ],
        )
        return True, deal["id"]
    return False, "That agreement has already moved on."


def authorized(state, npc, intent, future=False):
    if not npc.get("alive", True) or npc.get("down"):
        return False
    kind = intent.get("kind")
    if kind in ("give", "lend"):
        ids = intent.get("object_ids", [])
        return (
            bool(ids)
            and all(
                (o := state["objects"].get(i))
                and o.get("owner_id") == npc["id"]
                and o.get("holder_id") in (None, npc["id"])
                and o.get("condition") == "usable"
                and (future or o.get("holder_id") == npc["id"] or cast.distance(npc, o) <= tuning.REACH_CELLS)
                for i in ids
            )
            and (future or cast.distance(npc, state["player"]) <= tuning.REACH_CELLS)
        )
    if kind == "admit":
        return gatekeeping.can_admit(state, npc)
    if kind == "vouch":
        captain = cast.captain(state)
        return bool(captain and captain.get("alive", True) and not captain.get("down"))
    if kind == "physical":
        return bool(intent.get("task", "").strip())
    if kind == "help":
        return True
    if kind == "go":
        goal = intent.get("goal", [])
        return len(goal) == 2 and paths.grid(state).walkable(tuple(goal))
    return False


def execute(state, npc, intent, event):
    if not authorized(state, npc, intent):
        return False
    now = state["sim_time_ms"]
    kind = intent["kind"]
    if kind in ("give", "lend"):
        for oid in intent["object_ids"]:
            obj = state["objects"][oid]
            obj["holder_id"] = "player"
            if kind == "give":
                obj["owner_id"] = "player"
            else:
                obj["lent_to"] = "player"
            for slot in [s for s, i in npc.get("equipped", {}).items() if i == oid]:
                npc["equipped"].pop(slot)
    elif kind == "physical":
        cast.mind(npc)["physical_intention"] = intent["task"][:600]
        cast.add_pending(state, npc["id"], "decide", "their chosen physical work")
    elif kind == "help":
        cast.mind(npc).setdefault("commitments", []).append(
            {
                "id": f"help:{npc['id']}:{event}",
                "actor_id": npc["id"],
                "kind": "help",
                "task": intent.get("task", ""),
                "resource_ids": intent.get("object_ids", []),
                "status": "accepted",
                "until": now + 600000,
            }
        )
    elif kind == "vouch":
        gatekeeping.speak_for(
            state,
            npc,
            intent.get("task", "their own judgment"),
            f"{npc['name']} spoke for the stranger.",
            event,
            now,
            intent.get("task", ""),
        )
    elif kind == "admit":
        state.update(
            admitted={"by": npc["id"], "event_id": event, "because": [intent.get("task", "their own judgment")]},
            gate_open=True,
        )
    elif kind == "go":
        cast.set_job(npc, {"kind": "approach", "goal": intent["goal"], "speed": "walk", "stop": 0}, now)
    return True
