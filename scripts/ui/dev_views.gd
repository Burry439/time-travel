extends Node
## Developer views: the trace panel, one judge call, one exchange, and the journey's AI traces (F4).

const UITheme := preload("res://scripts/ui/ui_theme.gd")

var ui: Control # The UI (scripts/game_ui.gd), whose child this is.
var game: Node2D


# --- Developer views -----------------------------------------------------------------------------

## The developer's corner panel (F3): the journey's numbers, the gate switch, AI traces (F4).
func build_panel(root: Control) -> void:
	game.trace_panel = PanelContainer.new()
	game.trace_panel.theme_type_variation = "WoodPanel"
	game.trace_panel.position = Vector2(16, 128)
	game.trace_panel.custom_minimum_size = Vector2(290, 0)
	root.add_child(game.trace_panel)
	var debug_box := VBoxContainer.new()
	game.trace_panel.add_child(debug_box)
	game.trace_text = ui.label("", 13)
	game.trace_text.theme_type_variation = "WoodLabel"
	debug_box.add_child(game.trace_text)
	game.gate_button = ui.button("Open gate (test)", game.toggle_gate)
	debug_box.add_child(game.gate_button)
	debug_box.add_child(ui.button("AI traces  ·  F4", game.open_traces))
	game.trace_panel.hide()



## Developer-only view of one judge call: what was sent, what came back, what code changed.
func trace_view(body: Control, trace: Dictionary) -> void:
	if trace.get("kind") in ["talk", "round"] and not trace.has("judge"):
		talk_trace(body, trace)
		return
	var heading: Label = ui.label("DEVELOPER TRACE")
	heading.theme_type_variation = "Caption"
	body.add_child(heading)
	var judged: Dictionary = trace.get("judge", {})
	var validator: Dictionary = trace.get("validator", {})
	var summary := "Judge: %s  ·  model %s  ·  prompt %s  ·  reasoning %s\n%d ms  ·  %d in / %d out tokens  ·  %d attempt(s)" % [
		_shown(judged.get("status")), _shown(judged.get("model")), _shown(judged.get("prompt_version")),
		_shown(judged.get("reasoning")), int(judged.get("latency_ms", 0)), int(judged.get("input_tokens", 0)),
		int(judged.get("output_tokens", 0)), int(judged.get("attempts", 0))]
	if judged.get("error") != null:
		summary += "\nError: " + str(judged.error)
	for failure in judged.get("attempt_errors", []):
		summary += "\nAttempt error: " + str(failure)
	var proposed = judged.get("result")
	if typeof(proposed) == TYPE_DICTIONARY:
		summary += "\nModel proposed: %s  →  validator committed: %s" % [proposed.get("outcome"), validator.get("category")]
	else:
		summary += "\nValidator committed: " + str(validator.get("category"))
	var notes: Array = validator.get("notes", [])
	summary += "\nValidator notes: " + ("none (proposal accepted as is)" if notes.is_empty() else "")
	for note in notes:
		summary += "\n  • " + str(note)
	ui.small(body, summary)
	var raw = judged.get("raw_output")
	var parsed = JSON.parse_string(str(raw)) if raw != null else null
	reveal(body, "Model output (raw)", JSON.stringify(parsed, "  ") if parsed != null else str(raw))
	reveal(body, "Context sent to the model", JSON.stringify(trace.get("context", {}), "  "))
	if typeof(validator.get("new_spec")) == TYPE_DICTIONARY:
		reveal(body, "Object committed by code", JSON.stringify(validator.new_spec, "  "))


## Developer view of the last exchange: the move and reading the voice returned, how regard moved, what the voice was given.
func talk_trace(body: Control, trace: Dictionary) -> void:
	var call: Dictionary = trace.get("call", {})
	var spoken: Dictionary = trace.get("voice", {})
	var change: Dictionary = trace.get("regard_change", {})
	var heading: Label = ui.label("DEVELOPER: LAST EXCHANGE")
	heading.theme_type_variation = "Caption"
	body.add_child(heading)
	var reading: Dictionary = call.get("answers", {})
	var level := func(name: String) -> String:
		var value = reading.get(name, {})
		return "-" if typeof(value) != TYPE_DICTIONARY else str(value.get("score", value.get("noul", "-")))
	ui.small(body, ("Move: %s (the voice chose %s)\nReading: impression %s · suspicion %s · anger %s · believes %s"
		+ " · threat %s · reason %s\nTrust %+.2f · suspicion %+.2f\nVoice: %s · %s · %d ms%s") % [
		str(trace.get("action")), _shown(trace.get("voice_move")),
		level.call("impression"), level.call("suspicion"), level.call("anger"), level.call("believes"),
		level.call("threat"), level.call("reason"),
		float(change.get("trust", 0)), float(change.get("suspicion", 0)),
		_shown(spoken.get("status")), _shown(spoken.get("model")), int(spoken.get("latency_ms", 0)),
		("\nVoice error: " + str(spoken.error)) if spoken.get("error") != null else ""])
	reveal(body, "The person's situation", str(trace.get("situation", "")) + "\n\nREADING\n" +
		JSON.stringify(reading, "  "))
	reveal(body, "What the voice was given", JSON.stringify(trace.get("voice_context", {}), "  "))


func _shown(value) -> String:
	return "-" if value == null else str(value)


func reveal(body: Control, title: String, text: String) -> void:
	var box := TextEdit.new()
	box.text = text
	box.editable = false
	box.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	box.custom_minimum_size = Vector2(0, 220)
	box.add_theme_font_size_override("font_size", 13)
	box.visible = false
	var toggle: Button = ui.button("Show " + title.to_lower(), func() -> void: pass, "Quiet")
	toggle.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	toggle.pressed.connect(func() -> void:
		box.visible = not box.visible
		toggle.text = ("Hide " if box.visible else "Show ") + title.to_lower())
	body.add_child(toggle)
	body.add_child(box)


func show_traces(data: Dictionary) -> void:
	var body: VBoxContainer = ui.begin_modal("AI traces", "traces", Vector2(900, 600))
	var ai: Dictionary = data.get("ai", {})
	ui.paragraph(body, "AI mode: %s  ·  judge %s (%s)  ·  images %s (%s)\nPeople decide with: %s (%s)  ·  voice %s" % [
		ai.get("mode"), "on" if ai.get("judge") else "off", ai.get("judge_model"),
		"on" if ai.get("images") else "off", ai.get("image_model"), _shown(ai.get("decider")),
		_shown(ai.get("decider_model")), _shown(ai.get("voice_model"))])
	var traces: Array = data.get("traces", [])
	if traces.is_empty():
		ui.paragraph(body, "No attempts yet. Press T in the world and describe something to do.")
	for trace in traces:
		var title: Label = ui.label("“" + str(trace.get("text", "")) + "”", 17)
		title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		title.add_theme_color_override("font_color", ui.UITheme.ACCENT)
		body.add_child(title)
		trace_view(body, trace)
		body.add_child(HSeparator.new())
	var thoughts: Array = data.get("minds", [])
	if not thoughts.is_empty():
		var heading: Label = ui.label("PEOPLE'S DECISIONS (newest first)")
		heading.theme_type_variation = "Caption"
		body.add_child(heading)
		for thought in thoughts:
			var call: Dictionary = thought.get("call", {})
			var what := str(thought.get("action", thought.get("result", thought.get("skipped", "-"))))
			ui.small(body, "%s (%s) → %s\n%s · %s · %d ms · $%s%s%s" % [
				str(thought.npc_id).trim_prefix("npc_"), thought.get("why", ""), what, _shown(call.get("provider")),
				_shown(call.get("model")), int(call.get("latency_ms", 0)), _shown(call.get("cost_usd")),
				(" · one request for %d people" % int(thought.get("people_in_request", 1))) if thought.get("shared_request", false) else "",
				("\nFell back from " + str(call.fallback_from)) if call.get("fallback_from") != null else ""])
			reveal(body, "What %s's decider saw" % str(thought.npc_id).trim_prefix("npc_"),
				str(thought.get("situation", "")) + "\n\nOPTIONS AND ANSWERS\n" +
				JSON.stringify({"questions": thought.get("questions", {}), "answers": call.get("answers", {})}, "  "))
			if thought.get("kind") == "talk":
				var spoken: Dictionary = thought.get("voice", {})
				ui.small(body, "You: “%s”\nSaid: “%s”\nVoice: %s · %s · %d ms" % [thought.get("text", ""),
					thought.get("reply", ""), _shown(spoken.get("status")), _shown(spoken.get("model")),
					int(spoken.get("latency_ms", 0))])
				reveal(body, "What the voice was given", JSON.stringify(thought.get("voice_context", {}), "  "))
		body.add_child(HSeparator.new())
	var sprites: Array = data.get("assets", [])
	if not sprites.is_empty():
		var heading: Label = ui.label("SPRITES")
		heading.theme_type_variation = "Caption"
		body.add_child(heading)
		for sprite in sprites:
			var info: Dictionary = sprite.get("call", {})
			ui.small(body, "%s  ·  %s  ·  %s  ·  %d ms%s" % [sprite.get("record", {}).get("name"), sprite.status,
				_shown(info.get("model")), int(info.get("latency_ms", 0)),
				("\nError: " + str(info.error)) if info.get("error") != null else ""])
			if sprite.status in ["failed", "disabled"]:
				body.add_child(ui.button("Retry painting " + str(sprite.object_id), game.art.retry.bind(str(sprite.asset_id)), "Chip"))
			if info.has("prompt"):
				reveal(body, "Image prompt for " + str(sprite.object_id), str(info.prompt))
	var calls: Array = data.get("model_calls", [])
	if not calls.is_empty():
		var lines: PackedStringArray = []
		for entry in calls:
			lines.append("%s  %s  %d ms  %d/%d tok  %s" % [entry.role, _shown(entry.model), int(entry.latency_ms),
				int(entry.input_tokens), int(entry.output_tokens), "ok" if entry.ok else "FAILED"])
		reveal(body, "Model call log", "\n".join(lines))
	reveal(body, "Judge system prompt (" + str(data.get("judge_prompt_version", "")) + ")", str(data.get("judge_system_prompt", "")))
	reveal(body, "Voice system prompt", str(data.get("voice_system_prompt", "")))
