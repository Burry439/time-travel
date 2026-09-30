"""A decision that can't be made (network, TLS, a malformed reply) never takes a request down (28 Sep 500)."""

import json
from types import SimpleNamespace

from test_encounter import post, world  # noqa: F401
from test_intent import walk_near
from test_talk import said  # noqa: F401

from ai import config, decider, voice

REAL_DECIDE = decider.decide
REAL_SCENE = voice.scene


def break_everything(monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied", r"\\.\nllMonFltProxy\x")

    monkeypatch.setattr(decider, "mode", lambda: "llm")
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
    monkeypatch.setattr(voice, "scene", REAL_SCENE)
    monkeypatch.setattr(config, "mode", lambda: "live")  # A live game whose every call fails (not stub mode).
    break_everything(monkeypatch)
    # Classification falls back to speech; neither the decider nor the voice answers, so the honest answer is "nothing changed".
    body = post(world, state, "act", {"text": "Good evening, I'm new here.", "target_id": "npc_kade_east"}, status=503)
    assert body["detail"]["reason"] == "decider_failed" and "nothing changed" in body["detail"]["message"]
    assert world.http.get(f"/runs/{state['run_id']}").json()["event_seq"] == state["event_seq"]


class _Flaky:
    """A model client whose first structured answer is malformed and whose second is good."""

    def __init__(self, good):
        self.calls, self.good = 0, good
        self.responses = self

    def _next(self):
        self.calls += 1
        if self.calls == 1:
            return "bad"
        return self.good

    def parse(self, **kwargs):
        if self._next() == "bad":
            voice.Scene.model_validate_json('{"text": "Hm."}\n{"trailing": true}')  # Raises ValidationError.
        return SimpleNamespace(usage=None, output_parsed=self.good)

    def create(self, **kwargs):
        text = '{"kind": "a"} trailing' if self._next() == "bad" else '{"kind": "a"}'
        return SimpleNamespace(usage=None, output_text=text)


def test_one_malformed_answer_is_asked_again(monkeypatch):
    line = voice.SceneLine(
        speaker_id="npc_kade_east",
        text="Haven't seen her. Ask at the inn.",
        move="answer",
        impression="Unchanged",
        suspicion="Unchanged",
        anger="Calm",
        believes_what_was_said=True,
        sees_the_stranger_as_a_threat=False,
        reason_enough_to_let_them_through=False,
        agreed_to_the_deal=False,
        did_what_was_asked=False,
        errand_to="",
        errand_message="",
        promised_later="",
        remember="",
    )
    reply = voice.Scene(lines=[line], stranger_name="")
    flaky = _Flaky(reply)
    monkeypatch.setattr(config, "mode", lambda: "live")
    monkeypatch.setattr(config, "client", lambda: flaky)
    call = REAL_SCENE({"stranger_says": "Have you seen Hessa?"}, "fallback")
    assert call.status == "ok" and call.text.startswith("Haven't seen her") and flaky.calls == 2
    flaky = _Flaky(None)
    monkeypatch.setattr(config, "client", lambda: flaky)
    monkeypatch.setattr(decider, "mode", lambda: "llm")
    decided = REAL_DECIDE("A stranger waves.", {"kind": {"type": "choice", "criteria": {"a": "A", "b": "B"}}})
    assert decided.ok and decided.answers["kind"]["choice"] == "a" and flaky.calls == 2


class _Trailing:
    """A model client whose answer is complete and valid but followed by stray text (seen live, D-48)."""

    def __init__(self, whole: str):
        self.calls, self.whole = 0, whole
        self.responses = self

    def parse(self, **kwargs):
        self.calls += 1
        voice.Scene.model_validate_json(self.whole + " in final JSON schema")  # Raises ValidationError.


def test_a_whole_answer_with_stray_text_after_it_is_kept(monkeypatch):
    line = {
        "speaker_id": "npc_kade_east",
        "text": "Inn door.",
        "move": "answer",
        "impression": "Unchanged",
        "suspicion": "Unchanged",
        "anger": "Calm",
        "believes_what_was_said": True,
        "sees_the_stranger_as_a_threat": False,
        "reason_enough_to_let_them_through": False,
        "agreed_to_the_deal": False,
        "did_what_was_asked": False,
        "errand_to": "",
        "errand_message": "",
        "promised_later": "",
        "remember": "",
    }
    trailing = _Trailing(json.dumps({"lines": [line], "stranger_name": ""}))
    monkeypatch.setattr(config, "mode", lambda: "live")
    monkeypatch.setattr(config, "client", lambda: trailing)
    call = REAL_SCENE({"stranger_says": "Where's Hessa?"}, "fallback")
    assert call.status == "ok" and call.text == "Inn door." and trailing.calls == 1
