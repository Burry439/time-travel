"""The decider on OpenAI's Decisions API (D-71): our typed questions asked its way, its answers read back in the shape
every caller already reads, and the Responses way once more whenever it fails or refuses."""

from types import SimpleNamespace

import pytest

from ai import config, decider

QUESTIONS = {
    "kind": {"type": "choice", "criteria": {"say": "Only words.", "do": "A deed."}, "instructions": "Words or a deed?"},
    "anger": {"type": "score", "criteria": ["Calm", "Annoyed", "Angry", "Furious"], "instructions": "How angry?"},
    "speaks": {"type": "noul", "instructions": "Does the text include words said aloud?"},
}


def choice(name, picked, chances, confidence=0.9):
    probabilities = [SimpleNamespace(value=v, probability=p) for v, p in chances.items()]
    return SimpleNamespace(type="choice", name=name, choice=picked, probabilities=probabilities, confidence=confidence)


def score(name, chances, returned=9.9, confidence=0.6):
    probabilities = [SimpleNamespace(value=v, label=str(v), probability=p) for v, p in chances.items()]
    return SimpleNamespace(type="score", name=name, score=returned, probabilities=probabilities, confidence=confidence)


def predicate(name, probability):
    return SimpleNamespace(type="predicate", name=name, probability=probability)


GOOD = [choice("kind", "say", {"say": 0.8, "do": 0.2}), score("anger", {0: 0.5, 1: 0.5}), predicate("speaks", 0.92)]


class FakeClient:
    """Records each Decisions request and each Responses request; answers as told."""

    def __init__(self, answers=None, fail=None, responses_text='{"kind": "do", "anger": 2, "speaks": 0.3}'):
        self.answers, self.fail, self.responses_text = answers, fail, responses_text
        self.asked, self.responses_asked, self.limits = [], [], []
        self.decisions = SimpleNamespace(create=self._decide)
        self.responses = SimpleNamespace(create=self._respond)

    def _decide(self, **kwargs):
        self.asked.append(kwargs)
        if self.fail:
            raise self.fail
        return SimpleNamespace(answers=self.answers, usage=SimpleNamespace(input_tokens=400, output_tokens=0))

    def _respond(self, **kwargs):
        self.responses_asked.append(kwargs)
        return SimpleNamespace(
            output_text=self.responses_text, usage=SimpleNamespace(input_tokens=600, output_tokens=40)
        )


@pytest.fixture
def live(monkeypatch):
    def use(client):
        def bounded(limit=None):
            client.limits.append(limit)
            return client

        monkeypatch.setattr(decider, "mode", lambda: "llm")
        monkeypatch.setattr(config, "client", bounded)
        return client

    monkeypatch.setenv("DECIDER_BACKEND", "decisions")
    return use


def test_each_question_is_asked_the_decisions_way(live):
    client = live(FakeClient(GOOD))
    decider.decide("Typed: “hello there”", QUESTIONS)
    asked = client.asked[0]
    assert asked["model"] == decider.model()
    assert "SITUATION\nTyped: “hello there”" in asked["input"]  # The player's text stays inside the situation.
    kind, anger, speaks = asked["questions"]
    assert kind == {
        "type": "choice",
        "name": "kind",
        "instructions": "Words or a deed?",
        "choices": [{"value": "say", "description": "Only words."}, {"value": "do", "description": "A deed."}],
    }
    assert anger["type"] == "score" and [level["label"] for level in anger["levels"]] == ["0", "1", "2", "3"]
    assert anger["levels"][3]["description"] == "Furious"
    assert speaks == {"type": "predicate", "name": "speaks", "instructions": "Does the text include words said aloud?"}


def test_answers_come_back_in_the_shape_callers_read(live):
    live(FakeClient(GOOD))
    call = decider.decide("A stranger waves.", QUESTIONS)
    assert call.ok and call.provider == "decisions" and call.input_tokens == 400 and call.output_tokens == 0
    assert call.answers["kind"] == {
        "type": "choice",
        "choice": "say",
        "confidence": 0.9,
        "probabilities": {"say": 0.8, "do": 0.2},
    }
    # The level the probabilities point to, not the score the API returned (its documented example disagrees).
    assert call.answers["anger"]["score"] == pytest.approx(0.5) and call.answers["anger"]["confidence"] == 0.6
    assert call.answers["speaks"] == {"type": "noul", "noul": 0.92}


def test_a_list_of_choices_and_out_of_range_values_are_handled(live):
    questions = {"move": {"type": "choice", "criteria": ["wait", "leave"]}, "sure": {"type": "noul"}}
    live(FakeClient([choice("move", "leave", {"wait": 0.1, "leave": 0.9}), predicate("sure", 1.4)]))
    call = decider.decide("A stranger waves.", questions)
    assert call.answers["move"]["choice"] == "leave" and call.answers["sure"]["noul"] == 1.0


@pytest.mark.parametrize(
    "answers, why",
    [
        ([SimpleNamespace(type="refusal", name="kind"), *GOOD[1:]], "refused kind"),
        (GOOD[1:], "no usable answer to kind"),  # An answer missing.
        ([choice("kind", "fly", {"fly": 1.0}), *GOOD[1:]], "no usable answer to kind"),  # Not one of the options.
        ([predicate("kind", 0.5), *GOOD[1:]], "no usable answer to kind"),  # The wrong type of answer.
    ],
)
def test_a_refused_or_unusable_answer_is_asked_the_responses_way(live, answers, why):
    client = live(FakeClient(answers))
    call = decider.decide("A stranger waves.", QUESTIONS)
    assert len(client.asked) == 1 and len(client.responses_asked) == 1
    assert call.ok and call.provider == "llm" and call.fallback_from == f"decisions: {why}"
    assert call.answers["kind"]["choice"] == "do" and call.answers["speaks"]["noul"] == 0.3
    assert call.input_tokens == 1000  # Both attempts are counted.


def test_a_failed_decisions_call_falls_back_and_a_second_failure_is_honest(live):
    client = live(FakeClient(fail=TimeoutError("stuck"), responses_text="not json"))
    call = decider.decide("A stranger waves.", QUESTIONS)
    assert not call.ok and "JSONDecodeError" in call.error and call.fallback_from == "decisions: TimeoutError: stuck"
    assert len(client.asked) == 1 and len(client.responses_asked) == 2  # The Responses way retries a bad answer once.


def test_the_decisions_call_has_its_own_short_ceiling_inside_the_budget(live):
    client = live(FakeClient(GOOD))
    decider.decide("A stranger waves.", QUESTIONS)
    assert client.limits == [decider.DECISIONS_TIMEOUT_S]


def test_the_responses_backend_never_asks_the_decisions_way(live, monkeypatch):
    monkeypatch.setenv("DECIDER_BACKEND", "responses")
    client = live(FakeClient(GOOD))
    call = decider.decide("A stranger waves.", QUESTIONS)
    assert (
        call.ok and call.provider == "llm" and not client.asked and decider.status()["decider_backend"] == "responses"
    )


def test_stub_mode_asks_nobody(monkeypatch):
    monkeypatch.setattr(decider, "mode", lambda: "stub")
    monkeypatch.setattr(config, "client", lambda *a: (_ for _ in ()).throw(AssertionError("asked")))
    call = decider.decide("A stranger waves.", QUESTIONS)
    assert call.ok and call.provider == "stub" and call.answers["kind"]["choice"] == "say"


def test_the_client_ceiling_never_exceeds_what_is_left_of_the_budget(monkeypatch):
    monkeypatch.setattr(config, "api_key", lambda: "sk-test")
    monkeypatch.setattr(config, "remaining", lambda: 1.0)
    assert config.client(3.0).timeout == 1.0
    monkeypatch.setattr(config, "remaining", lambda: 9.0)
    assert config.client(3.0).timeout == 3.0 and config.client().timeout == 9.0
