"""People who weren't addressed don't cut in unless it's their business (D-71). Before their turn, each has a quick
check of their own: would they speak up, and does it give them reason to act? Only someone who would speak up takes a
turn that can speak; someone with reason to act thinks it over in silence; anyone else carries on. The check can only
keep someone quiet, and holds only what their own turn would hold."""

import json

import pytest
from test_agents import SECRETS, Recorder, at_the_gate
from test_encounter import world  # noqa: F401

import tuning
from ai import config, decider, voice

ROD, BREN, OREN = "npc_roderic_vale", "npc_bren_marr", "npc_oren_dast"


@pytest.fixture
def live(monkeypatch):
    """A live game whose voice is the recorder and whose checks answer as `verdicts` says: {id: (speaks_up, takes_note)},
    or {id: None} for a check that fails. Returns (recorder, asked checks)."""

    def use(verdicts):
        recorder, asked = Recorder(), []

        def check(state_text, questions, brief=""):
            payload = json.loads(state_text)
            me = payload["you"]["id"]
            asked.append({"me": me, "payload": payload, "text": state_text, "questions": questions, "brief": brief})
            if verdicts.get(me) is None:
                return decider.DeciderCall(provider="decisions", model="m", error="down")
            speaks_up, takes_note = verdicts[me]
            answers = {"speaks_up": {"noul": speaks_up}, "takes_note": {"noul": takes_note}}
            return decider.DeciderCall(provider="decisions", model="m", answers=answers, latency_ms=300)

        monkeypatch.setattr(config, "mode", lambda: "live")
        monkeypatch.setattr(config, "client", lambda *a: recorder)
        monkeypatch.setattr(voice.decider, "decide", check)
        monkeypatch.setenv("BYSTANDER_GATE", "on")
        return recorder, asked

    return use


def voiced(recorder):
    return [json.loads(made["input"][1]["content"])["you"]["id"] for made in recorder.calls]


def test_someone_with_no_reason_to_speak_or_act_takes_no_turn(live):
    recorder, asked = live({BREN: (0.1, 0.1), OREN: (0.2, 0.0)})
    call = voice.scene(at_the_gate()[1], "fallback")
    assert voiced(recorder) == [ROD]  # Only the person addressed was voiced.
    assert [line["speaker_id"] for line in call.lines] == [ROD] and call.decisions == []
    assert sorted(a["me"] for a in asked) == [BREN, OREN]  # The person addressed is never checked.
    assert {c["person_id"]: c["verdict"] for c in call.checks} == {BREN: "pass", OREN: "pass"}
    assert len(call.check_calls) == 2


def test_someone_with_reason_to_act_thinks_it_over_in_silence(live):
    recorder, _ = live({BREN: (0.2, 0.8), OREN: (0.1, 0.1)})
    call = voice.scene(at_the_gate()[1], "fallback")
    assert voiced(recorder) == [ROD, BREN]
    assert [line["speaker_id"] for line in call.lines] == [ROD]
    assert [d["speaker_id"] for d in call.decisions] == [BREN] and call.decisions[0]["text"] == ""
    assert call.decisions[0]["move"] == "answer"  # Their own decision still stands, to be applied silently.


def test_someone_whose_business_it_is_takes_their_turn_as_before(live):
    recorder, _ = live({BREN: (0.9, 0.0), OREN: (0.1, 0.1)})
    call = voice.scene(at_the_gate()[1], "fallback")
    assert voiced(recorder) == [ROD, BREN]
    assert [line["speaker_id"] for line in call.lines] == [ROD, BREN]


def test_someone_only_in_earshot_needs_more_reason_than_someone_taking_part(live):
    between = (tuning.SPEAK_UP_TAKING_PART + tuning.SPEAK_UP_NEARBY) / 2
    assert tuning.SPEAK_UP_TAKING_PART < between < tuning.SPEAK_UP_NEARBY
    _, context = at_the_gate()
    context["people"][2]["in_the_conversation"] = "taking part"  # Oren is in the conversation; Bren only near it.
    recorder, _ = live({BREN: (between, 0.0), OREN: (between, 0.0)})
    call = voice.scene(context, "fallback")
    assert {c["person_id"]: c["verdict"] for c in call.checks} == {BREN: "pass", OREN: "speak"}
    assert voiced(recorder) == [ROD, OREN]


def test_a_failed_check_or_the_gate_off_is_exactly_as_before(live, monkeypatch):
    recorder, _ = live({BREN: None, OREN: None})
    call = voice.scene(at_the_gate()[1], "fallback")
    assert voiced(recorder) == [ROD, BREN, OREN] and len(call.lines) == 3
    assert {c["verdict"] for c in call.checks} == {"unchecked"}
    recorder, asked = live({BREN: (0.0, 0.0), OREN: (0.0, 0.0)})
    monkeypatch.setenv("BYSTANDER_GATE", "off")
    call = voice.scene(at_the_gate()[1], "fallback")
    assert voiced(recorder) == [ROD, BREN, OREN] and not asked and not call.check_calls


def test_each_check_holds_only_that_persons_own_secrets_and_what_anyone_heard(live):
    _, asked = live({BREN: (0.1, 0.1), OREN: (0.1, 0.1)})
    voice.scene(at_the_gate()[1], "fallback")
    for made in asked:
        assert SECRETS[made["me"]] in made["text"]  # Their own: the same sheet their own turn would hold.
        assert not any(secret in made["text"] for who, secret in SECRETS.items() if who != made["me"])
        assert made["payload"]["said_just_now"] == ["Roderic: “I'm Roderic.”"]  # They heard the answer first.
        assert made["brief"] == voice.CHECK_BRIEF
        assert set(made["questions"]) == {"speaks_up", "takes_note"}
        assert all(q["type"] == "noul" for q in made["questions"].values())


def test_a_moments_checks_are_logged_as_decider_calls(world, monkeypatch):  # noqa: F811
    from test_talk import said

    import app as service
    import commands
    from ai import telemetry

    state = world.http.post("/runs", json={"mode": "developer"}).json()
    with commands.open(state["run_id"], playable=False, stale=False) as cmd:
        hessa = next(n for n in cmd.state["npcs"] if n["id"] == "npc_hessa_marr")
        cmd.state["player"].update(x=hessa["x"], y=hessa["y"] + 1)
        cmd.save("test-position", cmd.state["tick"])
        state = cmd.state
    original = service.voice.scene

    def with_checks(*args, **kwargs):
        call = original(*args, **kwargs)
        call.model = "gpt-6-luna"
        call.check_calls = [decider.DeciderCall(provider="decisions", model="gpt-6-luna", latency_ms=280)]
        return call

    monkeypatch.setattr(service.voice, "scene", with_checks)
    world.replies.append(said("answer"))
    reply = world.http.post(
        f"/runs/{state['run_id']}/say",
        json={
            "npc_id": "npc_hessa_marr",
            "text": "Good day.",
            "expected_version": state["event_seq"],
            "request_id": "checks-logged",
        },
    )
    assert reply.status_code == 200, reply.text
    with service.store.db() as connection:
        roles = [(row["role"], row["latency_ms"]) for row in telemetry.recent(connection, state["run_id"])]
    assert ("decider", 280) in roles and any(role == "voice" for role, _ in roles)
