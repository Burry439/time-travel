"""Scripted scenes for tests (D-48): a scripted reply (Jev-shaped answers with a "reply" move) becomes the addressed
person's line; a list of (speaker_id, reply) becomes a group moment in that order."""

from ai import voice


def scene_call(context: dict, scripted, text_for=None) -> voice.VoiceCall:
    addressed = context["people"][0]["id"]
    items = scripted if isinstance(scripted, list) else [(addressed, scripted)]
    lines = []
    for speaker, reply in items:
        person = next((p for p in context["people"] if p["id"] == speaker), context["people"][0])
        move = (reply.get("reply") or {}).get("choice", "answer")
        text = reply.get("text") or (
            text_for(context, person, move) if text_for else f"(voiced) {person['id']}: {move}"
        )
        lines.append(
            {
                "speaker_id": speaker,
                "text": text,
                "move": move,
                "story_beat": reply.get("story_beat", False),  # The line got the speaker's story beat across (D-59).
                "answers": reply,
                "remember": reply.get("remember", ""),
                "feelings": reply.get("feelings", []),  # [{person_id, change}] (D-59).
            }
        )
    return voice.VoiceCall(
        status="ok",
        text=lines[0]["text"],
        model="fake",
        lines=lines,
        stranger_name=items[0][1].get("name", "") if items else "",
    )
