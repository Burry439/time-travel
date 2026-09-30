"""Equipping, treating, and gear from what's made (D-49): code rules, events that replay."""

import copy

from test_craft import commit, fresh_state, judged
from test_encounter import post, world  # noqa: F401

import cast
import consequences
import gear
import judge_view
import perception
import reputation


def carried(state, oid, name, materials, mass, gear_record, flags=("rigid",), length=None):
    state["objects"][oid] = {
        "id": oid,
        "name": name,
        "x": 0,
        "y": 0,
        "mass_kg": mass,
        "owner_id": "player",
        "holder_id": "player",
        "capabilities": ["carry"],
        "bound_to": [],
        "water_l": 0.0,
        "capacity_l": 0.0,
        "condition": "usable",
        "materials": list(materials),
        "description": name,
        "flags": list(flags),
        "length_m": length,
        "gear": gear_record,
    }
    return state["objects"][oid]


def test_everyone_starts_in_their_own_gear_and_it_is_real():
    state = fresh_state()
    bren = cast.find(state["npcs"], "npc_bren_marr")
    assert gear.held(state, bren, "right")["name"] == "iron-headed spear"
    assert {layer["class"] for layer in gear.layers(state, bren, "body")} == {"mail"}
    assert gear.worn(state, state["player"], "body")["name"] == "travelling clothes"
    assert judge_view.people_nearby(fresh_state(bren["x"], bren["y"] + 1))  # (and the judge sees it, below)
    near = fresh_state(bren["x"], bren["y"] + 1)
    view = next(p for p in judge_view.people_nearby(near) if p["id"] == "npc_bren_marr")
    assert "mail shirt" in view["armour"] and "spear" in view["weapon"]


def test_a_downed_guards_sword_can_be_taken_and_that_is_theft():
    state = fresh_state()
    roderic = cast.find(state["npcs"], "npc_roderic_vale")
    state["player"].update(x=roderic["x"], y=roderic["y"] + 1)
    assert "sword_roderic" not in {o["id"] for o in judge_view.available_items(state)}  # On his hip, not yours.
    roderic.update(down=True, health=20)
    assert "sword_roderic" in {o["id"] for o in judge_view.available_items(state)}
    summary = commit(state, judged("take", take_ids=["sword_roderic"]))
    assert summary["category"] == "success" and state["objects"]["sword_roderic"]["holder_id"] == "player"
    assert summary["property"][0]["owner_id"] == "npc_roderic_vale"  # Theft, recorded against him.
    assert gear.held(state, roderic, "right") is None  # He no longer has it.


def test_what_is_made_gets_a_gear_class_that_fits_its_physics():
    state = fresh_state(45, 66)
    for item in ("branch_a", "flint_a", "vine_a"):
        state["objects"][item]["holder_id"] = "player"
    step = judged(
        "make",
        new_object={
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
            "capabilities": [{"text": "can pierce", "status": "expected"}],
            "gear": {"kind": "weapon", "gear_class": "long_sword", "covers": [], "quality": "good"},
        },
    )
    commit(state, step)
    made = state["objects"][state["last_action"]["crafted"]]
    assert made["gear"]["class"] == "short_spear"  # Not a sword: code's own reading of a 1.6 m flint point.
    assert gear.weapon(made)["type"] == "pierce"


def test_equipping_takes_time_and_replays(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    run = state["run_id"]
    body = post(world, state, "equip", {"object_id": "clothes_player", "slot": None})
    assert body["equip"]["ok"] and "body" not in body["state"]["player"]["equipped"]
    assert body["state"]["sim_time_ms"] == state["sim_time_ms"] + 10_000  # Clothes take a while.
    state = post(world, body["state"], "equip", {"object_id": "clothes_player", "slot": "body"})["state"]
    assert state["player"]["equipped"]["body"] == "clothes_player"
    nope = post(world, state, "equip", {"object_id": "clothes_player", "slot": "head"})
    assert not nope["equip"]["ok"] and nope["state"]["event_seq"] == state["event_seq"]  # Clothes go on the body.
    assert world.http.get(f"/runs/{run}").json() == nope["state"]


def test_treating_yourself_and_someone_else(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    run = state["run_id"]
    # A cut, and a bandage in the pack (set up directly in the saved run for the test).
    import store

    with store.lock, store.db() as connection:
        _, live = store.load_run(connection, run)
        live["player"]["conditions"] = [
            {"kind": "bleeding", "area": "arm", "severity": 20, "heavy": False, "since": 0, "treated": 0}
        ]
        carried(
            live,
            "bandage_test",
            "linen bandage",
            ["linen"],
            0.1,
            {"kind": "remedy", "class": "bandage", "covers": [], "quality": "fair"},
            flags=("flexible",),
        )
        connection.execute(
            "INSERT INTO checkpoints VALUES (?,?,?)", (run, live["event_seq"], __import__("json").dumps(live))
        )
    state = world.http.get(f"/runs/{run}").json()
    body = post(world, state, "treat", {"object_id": "bandage_test", "patient_id": "player", "condition": 0})
    assert body["treat"]["ok"], body
    state = body["state"]
    assert state["player"]["conditions"][0]["treated"] == 1 and gear.bleed_rate(state["player"]["conditions"][0]) == 0
    assert state["objects"]["bandage_test"]["holder_id"] == "used"  # Used up.
    assert world.http.get(f"/runs/{run}").json() == state


def test_treating_someone_earns_their_trust_like_a_gift():
    state = fresh_state()
    kade = cast.find(state["npcs"], "npc_kade_east")
    state["player"].update(x=kade["x"], y=kade["y"] + 1)
    kade["conditions"] = [{"kind": "bleeding", "area": "leg", "severity": 25, "heavy": False, "since": 0, "treated": 0}]
    carried(
        state,
        "bandage_kade",
        "linen bandage",
        ["linen"],
        0.1,
        {"kind": "remedy", "class": "bandage", "covers": [], "quality": "fair"},
        flags=("flexible",),
    )
    before = reputation.regard(kade)["trust"]
    payload, summary, after = consequences.resolve_attempt(
        state,
        "unit0000",
        "bind Kade's leg",
        {
            "clarifying_question": None,
            "precedent_key": "bind",
            "steps": [
                judged(
                    "treat", treat={"patient_id": "npc_kade_east", "remedy_id": "bandage_kade", "condition": "bleeding"}
                )
            ],
        },
        None,
        "t",
        0,
    )
    assert summary["category"] == "success"
    kade_after = cast.find(after["npcs"], "npc_kade_east")
    assert kade_after["conditions"][0]["treated"] == 1
    perception.apply_perceptions(after, perception.perceive(after, payload["journal_entry"]))
    kade_after = cast.find(after["npcs"], "npc_kade_east")
    assert reputation.regard(kade_after)["trust"] > before
    assert any(m["kind"] == "help" for m in kade_after["mind"]["memories"])


def test_putting_on_a_helmet_in_words_uses_the_same_rules():
    state = fresh_state()
    carried(
        state,
        "helm_test",
        "iron helmet",
        ["iron"],
        1.5,
        {"kind": "armour", "class": "helmet", "covers": ["head"], "quality": "fair"},
    )
    summary = commit(state, judged("equip", equip={"object_id": "helm_test", "slot": "head"}))
    assert summary["category"] == "success" and state["player"]["equipped"]["head"] == "helm_test"
    worse = commit(state, judged("equip", equip={"object_id": "helm_test", "slot": "feet"}))
    assert worse["category"] == "blocked"


def test_a_described_strangling_on_someone_unaware():
    state = fresh_state()
    oren = cast.find(state["npcs"], "npc_oren_dast")
    state["player"].update(x=oren["x"], y=oren["y"] + 1)
    carried(state, "cord_test", "cord", ["plant fiber"], 0.2, None, flags=("flexible", "tieable"), length=1.5)
    strangle = judged(
        "harm",
        harm={
            "target_id": "npc_oren_dast",
            "weapon_id": "cord_test",
            "method": "melee",
            "family": "choke",
            "outcome": "landed",
            "target_area": "neck",
            "held_seconds": 150,
            "result": "killed",
            "injury": "strangled",
        },
    )
    alert = copy.deepcopy(state)
    summary = commit(state, strangle)
    assert summary["harm"]["result"] == "killed" and not cast.find(state["npcs"], "npc_oren_dast")["alive"]
    cast.find(alert["npcs"], "npc_oren_dast").setdefault("mind", {})["facing_player"] = True  # He sees it coming.
    summary = commit(alert, strangle)
    assert summary["harm"]["result"] == "missed" and cast.find(alert["npcs"], "npc_oren_dast")["alive"]


def test_the_same_thing_made_twice_is_painted_once(tmp_path, monkeypatch):
    """The item library (D-49): an exact match reuses the pictures, with no second image call; anything that
    differs is painted anew."""
    from fastapi.testclient import TestClient
    from test_craft import PNG, spear, walk_to

    import app as service
    from ai import illustrator, judge

    monkeypatch.setattr(service.store, "DB_PATH", tmp_path / "lib.sqlite3")
    monkeypatch.setattr(service.attempts, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setattr(service.ai_config, "images_enabled", lambda: True)
    painted = []

    def fake_sprite(record, destination):
        painted.append(record)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(PNG)
        return illustrator.SpriteCall(status="ready", model="image-model", prompt=illustrator.sprite_prompt(record))

    monkeypatch.setattr(service.illustrator, "generate_sprite", fake_sprite)
    replies = []
    monkeypatch.setattr(
        service.judge,
        "judge_craft",
        lambda context: judge.JudgeCall(status="ok", result=replies.pop(0), model="stub", raw_output="{}", attempts=1),
    )
    http = TestClient(service.app)
    for run in range(2):
        state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
        replies.append(spear())
        reply = http.post(
            f"/runs/{state['run_id']}/craft",
            json={
                "text": "lash the flint to the branch",
                "selected_ids": [],
                "expected_version": state["event_seq"],
                "request_id": f"spear-{run}",
            },
        )
        assert reply.status_code == 200, reply.text
        made = reply.json()["state"]["objects"]["made_" + str(reply.json()["state"]["event_seq"])]
        assert made["held_asset_id"]  # A spear is drawn in the hand too.
        picture = http.get(f"/assets/{made['held_asset_id']}")
        assert picture.status_code == 200 and picture.content == PNG
    assert [r["view"] for r in painted] == ["world", "held"]  # The second spear came from the library.
    state = walk_to(http, http.post("/runs", json={"mode": "developer"}).json(), 45, 66)
    replies.append(spear(mass_kg=1.4))  # Lighter: a different thing.
    http.post(
        f"/runs/{state['run_id']}/craft",
        json={"text": "lash it", "selected_ids": [], "expected_version": state["event_seq"], "request_id": "other"},
    )
    assert len(painted) == 4
