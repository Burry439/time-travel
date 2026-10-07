"""Negotiated commitments. NPC satisfaction and physical truth are separate records.

A deal can be for one of the person's quest needs (D-73): then the quest settles it. When the quest step that answers
that need reaches them, code fulfils the deal and carries out its rewards, whether or not anyone says "done". One
result settles both records."""

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
                **({"for_need": need} if (need := _need_named(npc, proposal.get("for_quest", ""))) else {}),
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
    if action == "accept" and deal["status"] in ("proposed", "accepted"):
        deal.setdefault("accepted_event", event)
        deal.update(status="accepted")
        return True, deal["id"]
    # Doing what was asked accepts the deal: nobody need say "agreed" first (D-72: Hessa's deal stayed "offered",
    # so her judging the task done was refused and her words were replaced).
    if action == "satisfied" and deal["status"] in ("proposed", "accepted"):
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
    return False, f"That deal is already {deal['status']}; it can't be {action} now."


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


def _need_named(npc: dict, named: str) -> dict | None:
    """The quest need a deal is for, by the quest's title as the person sees it (or its id): {story, text}."""
    named = " ".join(str(named or "").split()).lower().rstrip(":")
    if not named:
        return None
    for story_id, need in ((npc.get("mind") or {}).get("needs") or {}).items():
        if named in (story_id.lower(), str(need.get("title", "")).lower()):
            return {"story": story_id, "title": need.get("title", ""), "text": need.get("text", "")}
    return None


HANDED = ("give", "lend")  # Rewards that change hands: only face to face.


def settle_for_need(state: dict, npc: dict, story_id: str, event: int, now: int) -> list[dict]:
    """The quest step that answers this person's need has reached them (D-73): every open deal of theirs for that
    need is fulfilled and its rewards carried out, as if they'd said "done". What changes hands waits until the
    stranger comes to them (they want a word: "I've what I promised you"). Returns the deals settled."""
    settled = []
    for deal in sorted(state.get("agreements", {}).values(), key=lambda d: d["id"]):
        if (
            deal.get("issuer") != npc["id"]
            or deal.get("status") not in ("proposed", "accepted")
            or (deal.get("for_need") or {}).get("story") != story_id
            or any(not authorized(state, npc, r, future=r["kind"] in HANDED) for r in deal["rewards"])
        ):
            continue
        owed = [r for r in deal["rewards"] if r["kind"] in HANDED and not authorized(state, npc, r)]
        for reward in deal["rewards"]:
            if reward not in owed:
                execute(state, npc, reward, event)
        deal.update(status="fulfilled", fulfilled_event=event, settled_by="quest", owed=owed)
        if owed:
            cast.want_word(npc, now, "Come and see me: I've what I promised you.")
        state.setdefault("journal", []).append(
            {
                "kind": "npc",
                "category": "deal_kept",
                "npc_id": npc["id"],
                "reason": f"{npc['name']} keeps their word: you were to {deal['task'].rstrip('.')}, and it's done.",
            }
        )
        settled.append(deal)
    return settled


def hand_over_owed(state: dict, npc: dict, event: int) -> None:
    """The stranger has come to them: what a settled deal owed them changes hands now, if it can (D-73)."""
    for deal in state.get("agreements", {}).values():
        if deal.get("issuer") == npc["id"] and deal.get("owed"):
            deal["owed"] = [r for r in deal["owed"] if not execute(state, npc, r, event)]


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
