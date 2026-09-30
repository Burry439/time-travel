extends Control
## The device from the future (GDD D-50): the small machine that brought the stranger here, and the only voice
## only they can hear. In the tutorial it speaks through the guide's cards (scripts/ui/tutorial_guide.gd, D-52);
## this panel shows only its answers when asked (H, from the guide's help). In the main game it speaks only when
## asked (H), or not at all if switched off. Its lines come from the saved state (device_log).

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const STEEL := Color(0.11, 0.16, 0.2, 0.93)
const GLOW := Color(0.55, 0.85, 0.95)
const TYPE_RATE := 55.0 # Characters per second.
const LINE_HOLD_S := 9.0
const QUEUED_HOLD_S := 3.5 # With more lines waiting, move on sooner.

var ui: Control
var game: Node2D
var story: Dictionary = {}
var panel: PanelContainer
var words: RichTextLabel
var badge: Label
var ask_box: LineEdit
var queue: Array[String] = []
var seen_lines := 0
var typing := ""
var shown_chars := 0.0
var hold := 0.0
var mode := "asked" # when asked | off (main game only; the tutorial always speaks)
var asking := false
var run_id := ""
var pulse := 0.0


func build(owner_ui: Control, owner_game: Node2D) -> void:
	ui = owner_ui
	game = owner_game
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var file := FileAccess.open("res://data/content/tutorial.json", FileAccess.READ)
	if file:
		story = JSON.parse_string(file.get_as_text())
	var settings := ConfigFile.new()
	if settings.load("user://presentation.cfg") == OK:
		mode = str(settings.get_value("device", "mode", "asked"))
	panel = PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = STEEL
	style.border_color = Color(GLOW, 0.55)
	style.set_border_width_all(1)
	style.set_corner_radius_all(6)
	style.content_margin_left = 12
	style.content_margin_right = 12
	style.content_margin_top = 8
	style.content_margin_bottom = 10
	panel.add_theme_stylebox_override("panel", style)
	panel.position = Vector2(16, 118)
	panel.custom_minimum_size = Vector2(380, 0)
	panel.size = Vector2(380, 0)
	panel.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 4)
	panel.add_child(column)
	badge = Label.new()
	badge.text = "◉  THE DEVICE  ·  H to ask"
	badge.add_theme_font_size_override("font_size", 11)
	badge.add_theme_color_override("font_color", GLOW)
	column.add_child(badge)
	words = RichTextLabel.new()
	words.fit_content = true
	words.bbcode_enabled = false
	words.scroll_active = false
	words.custom_minimum_size = Vector2(356, 0)
	words.add_theme_color_override("default_color", Color(0.86, 0.93, 0.96))
	words.add_theme_font_size_override("normal_font_size", 15)
	column.add_child(words)
	ask_box = LineEdit.new()
	ask_box.placeholder_text = "Ask the device anything, then Enter  (Esc to close)"
	ask_box.hide()
	ask_box.text_submitted.connect(_ask)
	ask_box.gui_input.connect(_ask_key)
	column.add_child(ask_box)
	panel.gui_input.connect(func(event: InputEvent) -> void:
		if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
			open_ask())
	panel.hide()


func in_tutorial() -> bool:
	var tutorial = game.run_state.get("tutorial")
	return typeof(tutorial) == TYPE_DICTIONARY and not tutorial.get("done", false)


func has_device() -> bool:
	return game.run_state.get("scenario", "village") == "tutorial" or mode != "off"


func set_mode(value: String) -> void:
	mode = value
	var settings := ConfigFile.new()
	settings.load("user://presentation.cfg")
	settings.set_value("device", "mode", value)
	settings.save("user://presentation.cfg")
	refresh()


## After every new state: new lines to say, the step clock, the closing card.
func refresh() -> void:
	var state: Dictionary = game.run_state
	if state.is_empty():
		panel.hide()
		return
	if str(state.get("run_id", "")) != run_id: # A different journey: start from what it has already said.
		run_id = str(state.get("run_id", ""))
		seen_lines = 0
		queue.clear()
		typing = ""
		var log: Array = state.get("device_log", [])
		seen_lines = maxi(0, log.size() - 2) # Replay only the last couple of lines on entering a journey.
	var lines: Array = state.get("device_log", [])
	for index in range(seen_lines, lines.size()):
		if not in_tutorial() or lines[index].has("question"): # The story's lines are the guide's cards (D-52).
			queue.append(str(lines[index].get("text", "")))
	seen_lines = lines.size()
	while queue.size() > 3: # Only the newest lines are worth reading (the journal has all).
		queue.pop_front()
	panel.visible = has_device() and (not typing.is_empty() or not queue.is_empty() or asking
		or (mode == "asked" and not in_tutorial()))


func _process(delta: float) -> void:
	if game == null or game.run_state.is_empty() or not game.gameplay_active:
		return
	pulse += delta
	badge.modulate.a = 0.75 + 0.25 * sin(pulse * 3.0) if not queue.is_empty() else 1.0
	# Type out the current line; hold it; then the next.
	if typing.is_empty() and not queue.is_empty():
		typing = queue.pop_front()
		shown_chars = 0.0
		hold = LINE_HOLD_S
		panel.show()
		ui.sounds.play("click")
	if not typing.is_empty():
		shown_chars = minf(typing.length(), shown_chars + delta * TYPE_RATE)
		words.text = typing.substr(0, int(shown_chars))
		if shown_chars >= typing.length():
			hold -= delta
			var waiting := not queue.is_empty() and LINE_HOLD_S - hold >= QUEUED_HOLD_S
			if (hold <= 0.0 and not queue.is_empty()) or waiting:
				typing = ""
			elif hold <= 0.0 and not asking:
				typing = ""
				words.text = ""
				panel.visible = has_device() and mode == "asked" and not in_tutorial()


## H: ask the device something.
func open_ask() -> void:
	if not has_device() or game.run_state.is_empty():
		return
	asking = true
	panel.show()
	ask_box.show()
	ask_box.text = ""
	ask_box.grab_focus()


func close_ask() -> void:
	asking = false
	ask_box.hide()
	ask_box.release_focus()


func _ask_key(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		ask_box.accept_event()
		close_ask()


func _ask(question: String) -> void:
	question = question.strip_edges()
	if question.is_empty():
		close_ask()
		return
	ask_box.editable = false
	queue.clear()
	typing = "…"
	shown_chars = 1.0
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/device/ask" % game.run_state.run_id, {
		"question": question, "expected_version": game.run_state.event_seq, "request_id": game._request_id("device")},
		60.0)
	ask_box.editable = true
	close_ask()
	typing = ""
	if not reply.ok:
		queue.append("…static. I can't answer just now.")
		return
	game._accept_state(reply.data.state)


## The first morning is over: carry on, or begin a fresh journey.
func closing_card() -> void:
	var settings := ConfigFile.new()
	settings.load("user://presentation.cfg")
	settings.set_value("tutorial", "done", true)
	settings.save("user://presentation.cfg")
	var body: VBoxContainer = ui.begin_modal("The first morning", "tutorial_end", Vector2(560, 300), false)
	ui.paragraph(body, "That's everything the device can teach you. The city gate is to the north, shut to strangers; how you get inside is up to you.\n\nYou can carry on from here, with everyone remembering this morning, or begin a fresh journey on the south road.")
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	body.add_child(row)
	row.add_child(ui.button("Carry on in this journey", func() -> void: ui.close_modal()))
	row.add_child(ui.button("Begin a fresh journey", func() -> void:
		ui.close_modal_now()
		game._start("normal")))
