"""Each person is their own agent (D-59). In a moment of conversation every person answers in a call of their own,
which holds only their own sheet, memory and secrets, what anyone there could see and hear, and the rules that
apply to them: the user asked whether everyone was "stuffed into one file", and they were (one call wrote everyone's
lines with every sheet, secrets and all, side by side)."""

import json
from types import SimpleNamespace

import app as service
import briefing
import cast
from ai import config, voice

SECRETS = {
    "npc_bren_marr": "covering Oren's late shifts",
    "npc_oren_dast": "owes Darin eleven silver",
    "npc_roderic_vale": "sent the scout out into the fog",
}


class Recorder:
    """A model client that records every call and answers as whoever the call is for."""

    def __init__(self):
        self.calls = []
        self.responses = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(kwargs["input"][1]["content"])
        line = voice.PersonLine(
            speaks=True,
            text=f"I'm {payload['you']['name']}.",
            brought_up_story_beat=False,
            move="answer",
            impression="Unchanged",
            suspicion="Unchanged",
            anger="Calm",
            believes_what_was_said=True,
            sees_the_stranger_as_a_threat=False,
            reason_enough_to_let_them_through=False,
            agreed_to_the_deal=False,
            did_what_was_asked=False,
            feelings_toward_others=[],
            errand_to="",
            errand_message="",
            promised_later="",
            remember="",
            stranger_name="",
        )
        return SimpleNamespace(usage=None, output_parsed=line)


def at_the_gate():
    state = service.initial_state(
        {
            "id": "agents00",
            "mode": "developer",
            "seed_version": service.SEED_VERSION,
            "geometry_version": service.GEOMETRY_VERSION,
        }
    )
    roderic, bren, oren = (cast.find(state["npcs"], i) for i in ("npc_roderic_vale", "npc_bren_marr", "npc_oren_dast"))
    return state, briefing.scene_context(state, roderic, [roderic], [bren, oren], "Who decides who goes in?", None)


def test_in_a_group_each_person_answers_in_their_own_call_with_only_their_own_secrets(monkeypatch):
    state, context = at_the_gate()
    recorder = Recorder()
    monkeypatch.setattr(config, "mode", lambda: "live")
    monkeypatch.setattr(config, "client", lambda: recorder)
    call = voice.scene(context, "fallback")
    speakers = ["npc_roderic_vale", "npc_bren_marr", "npc_oren_dast"]
    assert call.status == "ok" and len(recorder.calls) == 3 and [t["speaker_id"] for t in call.turns] == speakers
    assert call.lines[0] == {**call.lines[0], "speaker_id": "npc_roderic_vale", "text": "I'm Roderic."}
    for made in recorder.calls:
        prompt, payload = made["input"][0]["content"], json.loads(made["input"][1]["content"])
        me = payload["you"]["id"]
        text = json.dumps(payload, ensure_ascii=False)
        assert SECRETS[me] in text  # Their own secret: theirs to keep or tell.
        assert not any(secret in text for who, secret in SECRETS.items() if who != me)  # Nobody else's.
        assert "A HOLD-UP" not in prompt  # Nobody here is a robber: the robbers' rules aren't theirs.
        assert ("YOUR POST" in prompt) == (me in ("npc_roderic_vale", "npc_bren_marr", "npc_oren_dast"))  # Guards.
        assert payload["said_just_now"] == ([] if me == "npc_roderic_vale" else ["Roderic: “I'm Roderic.”"])


def test_a_person_who_stays_quiet_says_nothing():
    """Not addressed, a person speaks only when they choose to: a quiet turn is no line, and no failure."""

    class Quiet(Recorder):
        def parse(self, **kwargs):
            answer = super().parse(**kwargs)
            if json.loads(kwargs["input"][1]["content"])["your_part"] != "addressed":
                answer.output_parsed.speaks = False
            return answer

    _, context = at_the_gate()
    quiet = Quiet()
    config_mode, config_client = config.mode, config.client
    config.mode, config.client = (lambda: "live"), (lambda: quiet)
    try:
        call = voice.scene(context, "fallback")
    finally:
        config.mode, config.client = config_mode, config_client
    assert call.status == "ok" and [line["speaker_id"] for line in call.lines] == ["npc_roderic_vale"]
    assert [t["status"] for t in call.turns] == ["ok", "ok", "ok"]


class Lines:
    """A model client for one-line answers (a chat, an errand): records every call, answers as whoever it's for."""

    def __init__(self):
        self.calls = []
        self.responses = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(kwargs["input"][1]["content"])
        name = payload["you"]["name"]
        fields = {"line": f"{name} here."}
        if kwargs["text_format"] is voice.Heard:
            fields.update(move="carry_on", pass_on_message="", remember="")
        return SimpleNamespace(usage=None, output_parsed=kwargs["text_format"](**fields))


def test_a_chat_and_an_errand_are_each_side_in_their_own_call(monkeypatch):
    """Villagers chatting, and someone coming to tell someone something: the speaker and the listener each in a call
    of their own, the listener hearing what was said; neither sees the other's sheet or secrets."""
    import village

    state = service.initial_state(
        {
            "id": "agents01",
            "mode": "developer",
            "seed_version": service.SEED_VERSION,
            "geometry_version": service.GEOMETRY_VERSION,
        }
    )
    bren, oren = (cast.find(state["npcs"], i) for i in ("npc_bren_marr", "npc_oren_dast"))
    lines = Lines()
    monkeypatch.setattr(config, "mode", lambda: "live")
    monkeypatch.setattr(config, "client", lambda: lines)
    topic = {"kind": "news", "fact": "The well rope frayed.", "description": "The well rope frayed today."}
    chat = village.chatter_context(state, bren, oren, topic, {})
    call, said = voice.chatter(chat, ("", ""))
    assert call.status == "ok" and said == ("Bren here.", "Oren here.")
    hearing = village.hearing_context(state, oren, bren, "The stranger fixed the well rope.")
    call, heard = voice.hearing(hearing, village.fallback_hearing(oren, bren, "The stranger fixed the well rope."))
    assert call.status == "ok" and heard["teller_line"] == "Bren here." and heard["listener_line"] == "Oren here."
    assert len(lines.calls) == 4
    for made in lines.calls:
        payload = json.loads(made["input"][1]["content"])
        text = json.dumps(payload, ensure_ascii=False)
        me = {"Bren": "npc_bren_marr", "Oren": "npc_oren_dast"}[payload["you"]["name"]]
        assert not any(secret in text for who, secret in SECRETS.items() if who != me)
    assert json.loads(lines.calls[1]["input"][1]["content"])["they_said"] == "Bren here."  # Oren heard Bren.
