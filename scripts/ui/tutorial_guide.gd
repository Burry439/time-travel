extends Control
## The guide (GDD D-52): the tutorial as a hand-held, linear walk-through. Each step opens with the device's cards,
## big in the centre of the screen with the whole world paused, read at your own pace with Next (Enter or Space).
## Then one task sits on a banner at the top, and a pulsing ring (with an arrow at the screen's edge when it's out of
## sight) marks what the task is about. When it's done, a short praise card, then the next step's cards. Help comes
## only when asked (H, or "Stuck?"). "Type it for me" fills the dialogue bar with the suggested words.
## The backend counts a step only once its cards are read (POST tutorial/read); ui lessons are reported
## (POST tutorial/ui). Everything else is presentation, from data/content/tutorial.json.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const GLOW := Color(0.55, 0.85, 0.95)
const TEAL := Color(0.16, 0.42, 0.5)
const KEY_CAP := "[bgcolor=#3a2a18][color=#f3e6c8][b] %s [/b][/color][/bgcolor]"

var ui: Control
var game: Node2D
var story: Dictionary = {}
var steps: Array = []
var shade: ColorRect
var panel: PanelContainer
var header: Label
var words: RichTextLabel
var suggest_box: VBoxContainer
var suggest_words: Label
var type_button: Button
var back_button: Button
var next_button: Button
var ask_button: Button
var rewind_button: Button
var banner: PanelContainer
var banner_text: Label
var stuck_label: Button
var arrow: Control
var focus: Node2D
var pages: Array = [] # [{text, kind: card|done|help|reaction, step}]
var page := 0
var run_id := ""
var step_seen := -1
var log_seen := 0
var stuck_clock := 0.0
var sending := false


func build(owner_ui: Control, owner_game: Node2D) -> void:
	ui = owner_ui
	game = owner_game
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var file := FileAccess.open("res://data/content/tutorial.json", FileAccess.READ)
	if file:
		story = JSON.parse_string(file.get_as_text())
		steps = story.get("steps", [])
	arrow = Control.new()
	arrow.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	arrow.mouse_filter = Control.MOUSE_FILTER_IGNORE
	arrow.draw.connect(_draw_arrow)
	add_child(arrow)
	_build_banner()
	shade = ColorRect.new()
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.color = Color(0.03, 0.05, 0.06, 0.62)
	shade.mouse_filter = Control.MOUSE_FILTER_STOP # Nothing behind the card can be clicked.
	shade.hide()
	add_child(shade)
	_build_panel()
	focus = preload("res://scripts/ui/tutorial_focus.gd").new()
	focus.hide()
	game.add_child(focus)


func _build_banner() -> void:
	banner = PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.09, 0.14, 0.17, 0.92)
	style.border_color = Color(GLOW, 0.6)
	style.set_border_width_all(2)
	style.set_corner_radius_all(8)
	style.content_margin_left = 18
	style.content_margin_right = 18
	style.content_margin_top = 8
	style.content_margin_bottom = 8
	banner.add_theme_stylebox_override("panel", style)
	banner.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	banner.grow_horizontal = Control.GROW_DIRECTION_BOTH
	banner.offset_top = 14
	banner.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(banner)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	banner.add_child(row)
	banner_text = Label.new()
	banner_text.add_theme_font_size_override("font_size", 20)
	banner_text.add_theme_color_override("font_color", Color(0.9, 0.96, 0.98))
	banner_text.add_theme_font_override("font", UITheme.serif(true))
	row.add_child(banner_text)
	stuck_label = Button.new()
	stuck_label.text = "Stuck?  H"
	stuck_label.flat = true
	stuck_label.add_theme_font_size_override("font_size", 15)
	stuck_label.add_theme_color_override("font_color", GLOW)
	stuck_label.pressed.connect(open_help)
	row.add_child(stuck_label)
	banner.hide()


func _build_panel() -> void:
	panel = PanelContainer.new()
	panel.theme_type_variation = "PaperPanel"
	panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	panel.grow_horizontal = Control.GROW_DIRECTION_BOTH
	panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	panel.custom_minimum_size = Vector2(780, 0)
	panel.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 18)
	panel.add_child(column)
	header = Label.new()
	header.add_theme_font_size_override("font_size", 16)
	header.add_theme_color_override("font_color", TEAL)
	header.add_theme_font_override("font", UITheme.serif(true))
	column.add_child(header)
	words = RichTextLabel.new()
	words.bbcode_enabled = true
	words.fit_content = true
	words.scroll_active = false
	words.custom_minimum_size = Vector2(740, 120)
	words.add_theme_color_override("default_color", UITheme.INK)
	words.add_theme_font_size_override("normal_font_size", 25)
	words.add_theme_font_size_override("bold_font_size", 22)
	words.add_theme_font_override("normal_font", UITheme.serif())
	words.add_theme_constant_override("line_separation", 6)
	column.add_child(words)
	suggest_box = VBoxContainer.new()
	suggest_box.add_theme_constant_override("separation", 10)
	column.add_child(suggest_box)
	var quote := PanelContainer.new()
	quote.theme_type_variation = "InsetPanel"
	suggest_box.add_child(quote)
	suggest_words = Label.new()
	suggest_words.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	suggest_words.custom_minimum_size.x = 700
	suggest_words.add_theme_font_size_override("font_size", 24)
	suggest_words.add_theme_font_override("font", UITheme.serif(true, true))
	suggest_words.add_theme_color_override("font_color", UITheme.ACCENT)
	quote.add_child(suggest_words)
	type_button = ui.button("Type it for me", _type_it)
	type_button.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	suggest_box.add_child(type_button)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	column.add_child(row)
	back_button = ui.button("Back", _back)
	row.add_child(back_button)
	ask_button = ui.button("Ask the device something", func() -> void:
		_close()
		ui.device.open_ask())
	row.add_child(ask_button)
	rewind_button = ui.button("Rewind to the last calm moment", func() -> void:
		_close()
		game.rewind())
	row.add_child(rewind_button)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(spacer)
	next_button = ui.button("Next", _next)
	next_button.add_theme_font_size_override("font_size", 20)
	row.add_child(next_button)
	panel.hide()


## Is a card on screen? The whole world waits while one is (main.gd, game_ui.blocks_movement).
func is_open() -> bool:
	return panel.visible


func active() -> bool:
	var tutorial = game.run_state.get("tutorial")
	return typeof(tutorial) == TYPE_DICTIONARY and not tutorial.get("done", false)


func current_step() -> int:
	return int(game.run_state.get("tutorial", {}).get("step", 0)) if active() else -1


# --- Following the story -------------------------------------------------------------------------------------

## After every new state: a step done (its praise card), a new step (its cards), something drastic (a card).
func refresh() -> void:
	var state: Dictionary = game.run_state
	if state.is_empty():
		_close()
		banner.hide()
		return
	if str(state.get("run_id", "")) != run_id: # A different journey: pick up where it is.
		run_id = str(state.get("run_id", ""))
		step_seen = -1
		pages.clear()
		log_seen = state.get("device_log", []).size()
		_close()
	var lines: Array = state.get("device_log", [])
	for index in range(log_seen, lines.size()):
		if str(lines[index].get("kind", "")) == "reaction" and game.run_state.get("scenario") == "tutorial":
			pages.append({"text": str(lines[index].text), "kind": "reaction", "step": -1})
	log_seen = lines.size()
	var tutorial = state.get("tutorial")
	if typeof(tutorial) == TYPE_DICTIONARY:
		var step := int(tutorial.get("step", 0))
		var finished: bool = tutorial.get("done", false)
		if finished:
			step = steps.size()
		if step != step_seen:
			if step_seen >= 0:
				for passed in range(step_seen, mini(step, steps.size())):
					var done := str(steps[passed].get("done", ""))
					if not done.is_empty():
						pages.append({"text": done, "kind": "done", "step": passed})
			step_seen = step
			stuck_clock = 0.0
			if not finished and step < steps.size() and int(tutorial.get("read", step)) < step:
				for text in steps[step].get("cards", []):
					pages.append({"text": str(text), "kind": "card", "step": step})
	if not pages.is_empty() and not panel.visible:
		page = 0
		_show_page()
	_update_banner()


func _update_banner() -> void:
	var step := current_step()
	if step < 0 or step >= steps.size() or panel.visible or str(steps[step].get("task", "")).is_empty() \
			or int(game.run_state.tutorial.get("read", step)) < step:
		banner.hide()
		return
	banner_text.text = "%d / %d   ·   %s" % [step + 1, steps.size(), str(steps[step].task)]
	banner.show()


func _process(delta: float) -> void:
	if game == null or game.run_state.is_empty():
		focus.hide()
		arrow.queue_redraw()
		return
	if banner.visible and game.gameplay_active and not ui.blocks_movement():
		stuck_clock += delta
	var stuck := stuck_clock >= float(story.get("stuck_after_s", 60))
	stuck_label.modulate.a = (0.6 + 0.4 * sin(Time.get_ticks_msec() / 250.0)) if stuck else 1.0
	stuck_label.text = "Stuck? Press H" if stuck else "Stuck?  H"
	var target = _focus_target()
	focus.visible = target != null and banner.visible
	if focus.visible:
		focus.position = target
	arrow.queue_redraw()


## Where the ring goes: the step's spot, person, or the first of its things still lying in the world.
func _focus_target():
	var step := current_step()
	if step < 0 or step >= steps.size():
		return null
	var spec: Dictionary = steps[step].get("focus", {})
	if spec.has("cell"):
		return game._cell_center(int(spec.cell[0]), int(spec.cell[1]))
	if spec.has("npc"):
		var person := game.get_node_or_null("NPCs/" + str(spec.npc)) as Node2D
		return person.position if person else null
	var ids: Array = spec.get("objects", [])
	if spec.has("object"):
		ids = [spec.object]
	for id in ids:
		var obj: Dictionary = game.run_state.get("objects", {}).get(str(id), {})
		if obj.is_empty() or obj.get("holder_id") != null:
			continue
		var sprite := game.get_node_or_null("M2Objects/" + str(id)) as Node2D
		return sprite.position if sprite else game._cell_center(int(obj.x), int(obj.y))
	return null


## An arrow at the screen's edge when the marked thing is out of sight.
func _draw_arrow() -> void:
	if not focus.visible:
		return
	var screen: Vector2 = game.get_viewport().get_canvas_transform() * focus.position
	var view := get_viewport_rect().size
	var margin := 48.0
	if Rect2(Vector2(margin, margin), view - Vector2(margin, margin) * 2).has_point(screen):
		return
	var centre := view * 0.5
	var toward := (screen - centre).normalized()
	var edge := Vector2(clampf(screen.x, margin, view.x - margin), clampf(screen.y, margin + 60, view.y - margin - 90))
	var local: Vector2 = (edge - ui.root.position) / ui.ui_scale
	var tip: Vector2 = local + toward * 18.0
	var side := toward.orthogonal() * 14.0
	var shape := PackedVector2Array([tip, local - toward * 12.0 + side, local - toward * 12.0 - side])
	var glow := 0.75 + 0.25 * sin(Time.get_ticks_msec() / 200.0)
	arrow.draw_colored_polygon(shape, Color(GLOW, glow))
	arrow.draw_polyline(shape + PackedVector2Array([shape[0]]), Color(0.05, 0.12, 0.16), 2.0, true)


# --- The cards -----------------------------------------------------------------------------------------------

func _show_page() -> void:
	var entry: Dictionary = pages[page]
	var kind := str(entry.kind)
	var step := int(entry.get("step", -1))
	match kind:
		"card":
			header.text = "◉  THE DEVICE   ·   Step %d of %d   ·   %s" % [step + 1, steps.size(), str(steps[step].title)]
		"done":
			header.text = "◉  THE DEVICE   ·   Well done"
		"help":
			header.text = "◉  THE DEVICE   ·   A hint"
		_:
			header.text = "◉  THE DEVICE"
	words.text = keys(str(entry.text))
	var last := page == pages.size() - 1
	var suggest: Dictionary = steps[step].get("suggest", {}) if step >= 0 and step < steps.size() else {}
	var offer := last and kind in ["card", "help"] and not suggest.is_empty()
	suggest_box.visible = offer
	if offer:
		suggest_words.text = "%s  “%s”" % ["DO:" if str(suggest.get("mode", "say")) == "do" else "SAY:", str(suggest.text)]
		type_button.visible = bool(suggest.get("button", false))
	back_button.visible = page > 0
	ask_button.visible = last and kind == "help"
	rewind_button.visible = kind == "reaction"
	next_button.text = "Next  ›" if not last else ("Got it: let me try" if kind == "card" and
		not str(steps[step].get("task", "")).is_empty() else "Continue")
	shade.show()
	panel.show()
	banner.hide()
	ui.sounds.play("click")


## "{W}" and friends drawn as key caps.
static func keys(text: String) -> String:
	var out := text.replace("[", "(").replace("]", ")")
	var regex := RegEx.create_from_string("\\{([A-Za-z0-9\\- ]+)\\}")
	for found in regex.search_all(out):
		out = out.replace(found.get_string(), KEY_CAP % found.get_string(1))
	return out


func _next() -> void:
	if page < pages.size() - 1:
		page += 1
		_show_page()
	else:
		_finish()


func _back() -> void:
	if page > 0:
		page -= 1
		_show_page()


func _close() -> void:
	if panel == null:
		return
	var was_open := panel.visible
	panel.hide()
	shade.hide()
	if was_open and ui.bar.visible: # Back to the conversation where it was.
		ui.bar._focus_line.call_deferred()


## The cards are read: close them, and tell the story the current step's cards are read (so its task counts).
func _finish() -> void:
	var read_step := -1
	for entry in pages:
		if str(entry.kind) == "card":
			read_step = int(entry.step)
	pages.clear()
	_close()
	_update_banner()
	if read_step >= 0 and read_step == current_step():
		await _send("/runs/%s/tutorial/read" % game.run_state.run_id, {"step": read_step})
	_update_banner()


func _type_it() -> void:
	var step := int(pages[page].get("step", current_step()))
	var suggest: Dictionary = steps[step].get("suggest", {})
	await _finish()
	var person := str(suggest.get("to", "")) if suggest.get("to") != null else ""
	ui.bar.open(person, str(suggest.get("text", "")), {}, str(suggest.get("mode", "say" if not person.is_empty() else "do")))


## H in the tutorial: the step's written help, most specific last; the last card offers to ask the device.
func open_help() -> void:
	var step := current_step()
	if step < 0 or panel.visible:
		return
	for text in steps[step].get("help", ["Look around, and try what you know."]):
		pages.append({"text": str(text), "kind": "help", "step": step})
	stuck_clock = 0.0
	page = 0
	_show_page()


## Something the tutorial teaches happened on screen: the pack opened, a closer look, the journal, the book.
func report(key: String) -> void:
	if not active() or key in game.run_state.get("tutorial", {}).get("ui_done", []):
		return
	await _send("/runs/%s/tutorial/ui" % game.run_state.run_id, {"key": key})


func _send(path: String, body: Dictionary) -> void:
	if sending:
		return
	sending = true
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, path, body)
	sending = false
	if reply.ok:
		game._accept_state(reply.data.state)


func _input(event: InputEvent) -> void:
	if not panel.visible or not event is InputEventKey or not event.pressed or event.echo:
		return
	match event.keycode:
		KEY_ENTER, KEY_KP_ENTER, KEY_SPACE, KEY_RIGHT:
			_next()
		KEY_LEFT, KEY_BACKSPACE:
			_back()
	get_viewport().set_input_as_handled() # While a card is up, keys belong to it.
