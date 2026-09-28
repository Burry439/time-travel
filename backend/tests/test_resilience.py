"""A decision that can't be made (network, TLS, a malformed reply) never takes a request down (28 Sep 500)."""
import httpx

from ai import config, decider, voice
from test_encounter import post, world  # noqa: F401
from test_intent import walk_near
from test_talk import said  # noqa: F401

REAL_DECIDE = decider.decide
REAL_CONVERSE = voice.converse


def break_everything(monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied", r"\\.\nllMonFltProxy\x")
    monkeypatch.setattr(decider, "mode", lambda: "jev")
    monkeypatch.setattr(decider, "jev_key", lambda: "dk-test")
    monkeypatch.setattr(httpx, "post", refuse)
    monkeypatch.setattr(config, "client", refuse)


def test_the_decider_reports_failure_instead_of_raising(monkeypatch):
    break_everything(monkeypatch)
    call = REAL_DECIDE("A stranger waves.", {"kind": {"type": "choice", "criteria": {"a": "A", "b": "B"}}})
    assert not call.ok and "PermissionError" in call.error


def test_talk_still_works_when_every_model_call_fails(world, monkeypatch):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    state = walk_near(world, state, "npc_kade_east")
    monkeypatch.setattr(decider, "decide", REAL_DECIDE)
    monkeypatch.setattr(decider, "decide_many", lambda requests: [REAL_DECIDE(*r) for r in requests])
    monkeypatch.setattr(voice, "converse", REAL_CONVERSE)
    break_everything(monkeypatch)
    # Classification falls back to speech; neither Jev nor the voice answers, so the honest answer is "nothing changed".
    body = post(world, state, "act", {"text": "Good evening, I'm new here.", "target_id": "npc_kade_east"}, status=503)
    assert body["detail"]["reason"] == "decider_failed" and "nothing changed" in body["detail"]["message"]
    assert world.http.get(f"/runs/{state['run_id']}").json()["event_seq"] == state["event_seq"]
