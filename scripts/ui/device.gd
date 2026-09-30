extends Control
## The device from the future (GDD D-50, D-55): the small machine that brought the stranger here, the only voice
## only they can hear, and their coach. Always there: a small widget under the goal (click it, or H) opens the
## Device window, with everything the two of you have ever said, quick questions and a line to ask anything. It
## remembers your conversations (the backend gives it the last exchanges) and, unless set to "only when asked", it
## speaks up at moments that matter (a new lead, a failure, someone angry, word spreading, being stuck), at most
## every two minutes. In the tutorial its story lines are the guide's cards (tutorial_guide.gd, D-52).
## Everything it says comes from the saved state (device_log), so the history survives reloads.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const STEEL := Color(0.10, 0.15, 0.19, 0.94)
const GLOW := Color(0.55, 0.85, 0.95)
const TYPE_RATE := 60.0 # Characters per second.
const LINE_HOLD_S := 12.0
const MOMENT_GAP_S := 120.0 # Speaks up on its own at most this often (the server checks too).
const STUCK_AFTER_S := 240.0
const QUICK := ["What should I do next?", "Why did that fail?", "Who could help me?", "How do the controls work?"]

var ui: Control
var game: Node2D
var story: Dictionary = {}
var panel: PanelContainer
var words: RichTextLabel
var badge: Label
var queue: Array[String] = []
var seen_lines := 0
var typing := ""
var shown_chars := 0.0
var hold := 0.0
var mode := "speaks" # speaks | asked (D-55: always there; it can only be quieter)
var run_id := ""
var pulse := 0.0
# The window, while it is open.
var history_box: VBoxContainer
var history_scroll: ScrollContainer
var ask_line: LineEdit
var asking := false
# Moments worth a word (D-55): what was already seen, so only new things count.
var seen_leads := -1
var seen_attempts := -1
var seen_angry: Array[String] = []
var seen_tellers: Array[String] = []
var progress_mark := ""
var stuck_clock := 0.0
var last_moment_s := -1000.0


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
		mode = "asked" if str(settings.get_value("device", "mode", "speaks")) in ["asked", "off"] else "speaks"
	panel = PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = STEEL
	style.border_color = Color(GLOW, 0.55)
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	style.content_margin_left = 12
	style.content_margin_right = 12
	style.content_margin_top = 7
	style.content_margin_bottom = 8
	panel.add_theme_stylebox_override("panel", style)
	panel.position = Vector2(16, 118)
	panel.custom_minimum_size = Vector2(310, 0)
	panel.mouse_filter = Control.MOUSE_FILTER_STOP
	panel.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	panel.tooltip_text = "The device: click (or H) to talk to it"
	add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 3)
	panel.add_child(column)
	badge = Label.new()
	badge.text = "◉  THE DEVICE   ·   H to talk"
	badge.add_theme_font_size_override("font_size", 12)
	badge.add_theme_color_override("font_color", GLOW)
	column.add_child(badge)
	words = RichTextLabel.new()
	words.fit_content = true
	words.bbcode_enabled = false
	words.scroll_active = false
	words.custom_minimum_size = Vector2(340, 0)
	words.add_theme_color_override("default_color", Color(0.88, 0.94, 0.97))
	words.add_theme_font_size_override("normal_font_size", 15)
	words.hide()
	column.add_child(words)
	panel.gui_input.connect(func(event: InputEvent) -> void:
		if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
			open_ask())
	panel.hide()


func in_tutorial() -> bool:
	var tutorial = game.run_state.get("tutorial")
	return typeof(tutorial) == TYPE_DICTIONARY and not tutorial.get("done", false)


func set_mode(value: String) -> void:
	mode = "asked" if value == "asked" else "speaks"
	var settings := ConfigFile.new()
	settings.load("user://presentation.cfg")
	settings.set_value("device", "mode", mode)
	settings.save("user://presentation.cfg")
	refresh()


## After every new state: new lines to show, moments worth a word, and the window if it's open.
func refresh() -> void:
	var state: Dictionary = game.run_state
	if state.is_empty():
		panel.hide()
		return
	if str(state.get("run_id", "")) != run_id: # A different journey: start from what it has already said.
		run_id = str(state.get("run_id", ""))
		queue.clear()
		typing = ""
		words.hide()
		seen_lines = state.get("device_log", []).size()
		seen_leads = -1
		seen_attempts = -1
		seen_angry.clear()
		seen_tellers.clear()
		stuck_clock = 0.0
	var lines: Array = state.get("device_log", [])
	for index in range(seen_lines, lines.size()):
		var line: Dictionary = lines[index]
		if str(line.get("kind", "")) in ["answer", "remark"] and ui.modal_kind != "device":
			queue.append(str(line.get("text", "")))
	seen_lines = lines.size()
	while queue.size() > 2:
		queue.pop_front()
	panel.visible = not in_tutorial() or not queue.is_empty() or not typing.is_empty()
	_place()
	_watch_moments(state)
	if ui.modal_kind == "device" and is_instance_valid(history_box) and not asking:
		_render_history()


## Just under the goal panel, whatever its height.
func _place() -> void:
	var goal_panel: Control = ui.hud.objective
	var below := 118.0
	if goal_panel and goal_panel.visible:
		below = goal_panel.position.y + goal_panel.size.y + 8.0
	panel.position = Vector2(16, below)


func _process(delta: float) -> void:
	if game == null or game.run_state.is_empty():
		return
	pulse += delta
	badge.modulate.a = 0.75 + 0.25 * sin(pulse * 3.0) if not queue.is_empty() or not typing.is_empty() else 1.0
	if typing.is_empty() and not queue.is_empty():
		typing = queue.pop_front()
		shown_chars = 0.0
		hold = LINE_HOLD_S
		words.show()
		panel.show()
		ui.sounds.play("click")
	if not typing.is_empty():
		shown_chars = minf(typing.length(), shown_chars + delta * TYPE_RATE)
		words.text = typing.substr(0, int(shown_chars))
		if shown_chars >= typing.length():
			hold -= delta
			if hold <= 0.0 or (not queue.is_empty() and hold <= LINE_HOLD_S - 4.0):
				typing = ""
				if queue.is_empty():
					words.hide()
					panel.visible = not in_tutorial()
	# Stuck: nothing has moved on for a while (no new lead, nothing made, nobody's view of you changed).
	if not in_tutorial() and mode == "speaks" and game.gameplay_active and not ui.blocks_movement():
		stuck_clock += delta
		if stuck_clock >= STUCK_AFTER_S:
			stuck_clock = 0.0
			_moment("stuck")


# --- The window --------------------------------------------------------------------------------------------------

## H, or a click on the widget: the Device window, with everything you've said to each other.
func open_ask() -> void:
	if game.run_state.is_empty():
		return
	var body: VBoxContainer = ui.begin_modal("◉  The device", "device", Vector2(820, 640), false)
	var intro := Label.new()
	intro.text = "Only you can hear it. It remembers everything the two of you have said."
	intro.theme_type_variation = "Small"
	body.add_child(intro)
	history_scroll = ScrollContainer.new()
	history_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	history_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body.add_child(history_scroll)
	history_box = VBoxContainer.new()
	history_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	history_box.add_theme_constant_override("separation", 8)
	history_scroll.add_child(history_box)
	var quick := HFlowContainer.new()
	quick.add_theme_constant_override("h_separation", 6)
	quick.add_theme_constant_override("v_separation", 6)
	body.add_child(quick)
	for question in QUICK:
		quick.add_child(ui.button(question, _ask.bind(question), "Chip"))
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	body.add_child(row)
	ask_line = LineEdit.new()
	ask_line.placeholder_text = "Ask it anything…"
	ask_line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	ask_line.custom_minimum_size.y = 40
	ask_line.add_theme_font_size_override("font_size", 17)
	ask_line.text_submitted.connect(_ask)
	row.add_child(ask_line)
	row.add_child(ui.button("Ask", func() -> void: _ask(ask_line.text)))
	queue.clear() # Its lines are all here now.
	typing = ""
	words.hide()
	_render_history()
	ask_line.grab_focus.call_deferred()


func close_ask() -> void:
	if ui.modal_kind == "device":
		ui.close_modal()


func _render_history() -> void:
	for child in history_box.get_children():
		history_box.remove_child(child)
		child.queue_free()
	var lines: Array = game.run_state.get("device_log", [])
	if lines.is_empty():
		history_box.add_child(_bubble("Ask me anything: what to do next, why something failed, how things work here. "
			+ "I'll tell you what I can.", false, ""))
	for line in lines:
		if line.has("question"):
			history_box.add_child(_bubble(str(line.question), true, _clock(int(line.get("at", 0)))))
		var tag := "" if line.has("question") else ("  ·  spoke up" if str(line.get("kind", "")) == "remark" else "")
		history_box.add_child(_bubble(str(line.get("text", "")), false, _clock(int(line.get("at", 0))) + tag))
	_scroll_down.call_deferred()


func _bubble(text: String, mine: bool, stamp: String) -> Control:
	var row := HBoxContainer.new()
	var spacer := Control.new()
	spacer.custom_minimum_size.x = 90
	var bubble := PanelContainer.new()
	bubble.add_theme_stylebox_override("panel", UITheme.flat(UITheme.PARCHMENT_DARK if mine else STEEL,
		UITheme.GOLD_DIM if mine else Color(GLOW, 0.5), 1, 10))
	bubble.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 2)
	bubble.add_child(column)
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", 16)
	label.add_theme_color_override("font_color", UITheme.INK if mine else Color(0.9, 0.95, 0.97))
	column.add_child(label)
	if not stamp.is_empty():
		var small := Label.new()
		small.text = ("You  ·  " if mine else "◉  ") + stamp
		small.add_theme_font_size_override("font_size", 11)
		small.add_theme_color_override("font_color", UITheme.INK_SOFT if mine else Color(GLOW, 0.8))
		column.add_child(small)
	if mine:
		row.add_child(spacer)
		row.add_child(bubble)
	else:
		row.add_child(bubble)
		row.add_child(spacer)
	return row


func _clock(ms: int) -> String:
	var minutes := ms / 60000
	return "%d min into the day" % minutes if minutes > 0 else "the start of the day"


func _scroll_down() -> void:
	await get_tree().process_frame
	if is_instance_valid(history_scroll):
		history_scroll.scroll_vertical = int(history_scroll.get_v_scroll_bar().max_value)


func _ask(question: String) -> void:
	question = question.strip_edges()
	if question.is_empty() or asking:
		return
	asking = true
	if is_instance_valid(ask_line):
		ask_line.text = ""
		ask_line.editable = false
	if is_instance_valid(history_box):
		history_box.add_child(_bubble(question, true, "now"))
		history_box.add_child(_bubble("…", false, ""))
		_scroll_down.call_deferred()
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/device/ask" % game.run_state.run_id, {
		"question": question, "expected_version": game.run_state.event_seq, "request_id": game._request_id("device")},
		60.0)
	asking = false
	if is_instance_valid(ask_line):
		ask_line.editable = true
		ask_line.grab_focus()
	if not reply.ok:
		if is_instance_valid(history_box):
			history_box.add_child(_bubble("…static. I can't answer just now. Ask me again in a moment.", false, ""))
		return
	game._accept_state(reply.data.state)
	if ui.modal_kind == "device" and is_instance_valid(history_box):
		_render_history()


# --- Speaking up at moments that matter (D-55) --------------------------------------------------------------------

func _watch_moments(state: Dictionary) -> void:
	var leads: int = state.get("learned", []).filter(func(e) -> bool: return not str(e.get("lead", "")).is_empty()).size()
	var attempts: Array = state.get("journal", []).filter(func(e) -> bool: return e.get("kind") == "craft")
	var angry: Array[String] = []
	var tellers: Array[String] = []
	var standings := PackedStringArray()
	for npc in state.get("npcs", []):
		var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		if float(their_mind.get("feelings", {}).get("anger", 0.0)) >= 0.67 and npc.get("alive", true):
			angry.append(str(npc.id))
		var job = their_mind.get("job")
		if typeof(job) == TYPE_DICTIONARY and str(job.get("kind", "")) == "tell":
			tellers.append(str(npc.id))
		standings.append(str(their_mind.get("standing", "")))
	var made: int = state.get("objects", {}).values().filter(func(o) -> bool: return o.get("created_by") == "player").size()
	var mark := "%d|%d|%s" % [leads, made, ",".join(standings)]
	if mark != progress_mark:
		progress_mark = mark
		stuck_clock = 0.0
	var moment := ""
	if seen_leads >= 0 and leads > seen_leads:
		moment = "new_lead"
	elif seen_attempts >= 0 and attempts.size() > seen_attempts and \
			str(attempts[-1].get("category", "")) in ["failed", "blocked", "unsupported", "unresolved"]:
		moment = "failure"
	elif angry.any(func(id) -> bool: return not id in seen_angry):
		moment = "angry"
	elif tellers.any(func(id) -> bool: return not id in seen_tellers):
		moment = "news"
	seen_leads = leads
	seen_attempts = attempts.size()
	seen_angry = angry
	seen_tellers = tellers
	if not moment.is_empty():
		_moment(moment)


func _moment(kind: String) -> void:
	var now := Time.get_ticks_msec() / 1000.0
	if in_tutorial() or mode != "speaks" or now - last_moment_s < MOMENT_GAP_S or game.run_state.is_empty() \
			or game.in_fight() or game.in_encounter():
		return
	last_moment_s = now
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/device/ask" % game.run_state.run_id, {
		"moment": kind, "expected_version": game.run_state.event_seq, "request_id": game._request_id("device")}, 60.0)
	if reply.ok and not reply.data.get("skipped", false):
		game._accept_state(reply.data.state)


## The first morning is over: carry on, or begin a fresh journey.
func closing_card() -> void:
	var settings := ConfigFile.new()
	settings.load("user://presentation.cfg")
	settings.set_value("tutorial", "done", true)
	settings.save("user://presentation.cfg")
	var admitted = game.run_state.get("admitted")
	var by := str(ui.npc_record(str(admitted.get("by", ""))).get("name", "")) if typeof(admitted) == TYPE_DICTIONARY else ""
	var body: VBoxContainer = ui.begin_modal("The first morning", "tutorial_end", Vector2(600, 330), false)
	var opening := ("You're in: %s has let you into the city. That's how it works here: people watch what you do, "
		+ "pass it on, and speak for you.\n\n") % by if not by.is_empty() else "That's everything the device can teach you.\n\n"
	ui.paragraph(body, opening + "A fresh journey starts again on the south road, with other people's problems and "
		+ "nobody handing you the answer. The device stays with you: press H any time to talk to it.")
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	body.add_child(row)
	row.add_child(ui.button("Walk into the city" if not by.is_empty() else "Carry on in this journey", func() -> void: ui.close_modal()))
	row.add_child(ui.button("Begin a fresh journey", func() -> void:
		ui.close_modal_now()
		game._start("normal")))
