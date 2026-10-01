"""What the client is shown from the world (views.py, D-58): leads done or not, deeds, the standing words, carried
by every reply that carries a state."""

from test_encounter import world  # noqa: F401
from test_talk import npc, unit_state

import app as service
import reputation
import views


def test_a_lead_is_done_when_what_it_points_to_has_happened():
    state = unit_state()
    tomas, hessa = npc(state, "npc_tomas_reed"), npc(state, "npc_hessa_marr")
    state["agreements"] = {"deal_1": {"id": "deal_1", "issuer": tomas["id"], "status": "accepted", "task": "raise it"}}
    state["objects"]["bucket_hessa"].update(holder_id="player", lent_to="player")
    state["learned"] = [
        {"npc_id": tomas["id"], "lead": "Tomas's request", "offer": "deal_1"},
        {"npc_id": hessa["id"], "lead": "Hessa lent you her bucket", "lend": "bucket_hessa"},
        {"npc_id": hessa["id"], "lead": "Talk to Mara", "refer": "npc_mara_venn"},
        {"npc_id": hessa["id"], "lead": "The well is dry", "fact": "well"},
        {"npc_id": hessa["id"], "lead": "Hessa gave you a cup", "gift": "cup"},
    ]
    assert views.of(state)["lead_done"] == [False, False, False, False, True]
    state["agreements"]["deal_1"]["status"] = "fulfilled"
    state["objects"]["bucket_hessa"].update(holder_id=hessa["id"])  # Given back.
    npc(state, "npc_mara_venn").setdefault("mind", {})["met"] = True
    assert views.of(state)["lead_done"][:3] == [True, True, True]


def test_deeds_come_from_what_really_happened():
    state = unit_state()
    assert views.deeds(state) == []
    hessa, kade = npc(state, "npc_hessa_marr"), npc(state, "npc_kade_east")
    state["objects"]["made_9"] = {
        **state["objects"]["bucket_hessa"],
        "id": "made_9",
        "name": "clay bowl",
        "created_by": "player",
    }
    reputation.remember(
        hessa,
        {
            "kind": "gift",
            "victim": hessa["id"],
            "clarity": "clear",
            "severity": 1,
            "summary": "a bowl",
            "short": "gave me a bowl",
            "source": "received",
        },
    )
    reputation.remember(
        kade,
        {
            "kind": "demonstration",
            "wonder": "uncanny",
            "clarity": "clear",
            "item": "fire",
            "severity": 1,
            "summary": "fire",
            "short": "made fire",
            "source": "witnessed",
        },
    )
    state["agreements"] = {
        "deal_2": {"id": "deal_2", "issuer": hessa["id"], "status": "fulfilled", "task": "fetch water"}
    }
    state["admitted"] = {"by": "npc_roderic_vale"}
    ids = [d["id"] for d in views.deeds(state)]
    assert ids[0] == "first_made" and "helped:npc_hessa_marr" in ids and "amazed:npc_kade_east" in ids
    assert "deal:deal_2" in ids and "kept:deal_2" in ids and ids[-1] == "admitted"
    amazed = next(d for d in views.deeds(state) if d["id"] == "amazed:npc_kade_east")
    assert (
        amazed["text"] == "Kade saw your fire work, and has never seen anything like it."
        and amazed["who"] == kade["id"]
    )


def test_every_reply_with_a_state_carries_its_view_and_the_save_never_does(world):  # noqa: F811
    state = world.http.post("/runs", json={}).json()
    assert state["view"]["standing_words"] == reputation.STANDING_WORDS and state["view"]["deeds"] == []
    moved = world.http.post(
        f"/runs/{state['run_id']}/move",
        json={"x": 48, "y": 67, "expected_version": state["event_seq"], "request_id": "view-step"},
    ).json()
    assert "view" in moved["state"]
    with service.db() as connection:
        rows = connection.execute("SELECT payload FROM events WHERE run_id=?", (state["run_id"],)).fetchall()
    assert rows and all(b"view" not in bytes(row["payload"]) for row in rows)
