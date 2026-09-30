extends Control
## The UI coordinator (GDD D-35). It owns the wood and parchment theme and UI scale, and puts
## together the HUD (scripts/ui/hud.gd), the dialogue bar (action_bar.gd), the inspect card,
## the journal book, menus and the developer views. It also holds the shared formatting
## helpers (object icons, provenance, result wording).

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const CAPABILITY_NOTES := {"expected": "", "untested": "  (untested)", "observed": "  (seen working)",
	"failed": "  (didn't work when tried)"}
const OUTCOME_TITLES := {
	"success": "You made something", "failed": "It didn't work", "blocked": "Something is missing",
	"needs_clarification": "One question", "unsupported": "Beyond this world's rules",
	"unresolved": "Nothing was decided", "partial_success": "Partly done",
}
const FLAG_WORDS := {
	"rigid": "rigid", "flexible": "flexible", "sharp_edge": "sharp", "tieable": "can be tied",
	"adhesive": "sticky", "container": "holds things", "watertight": "watertight", "floats": "floats",
	"combustible": "would burn", "ferromagnetic": "attracted to magnets", "magnetized": "magnetic",
	"magnet_source": "strongly magnetic", "light_source": "gives light", "heat_source": "gives heat",
	"sound_loud": "loud", "reflective": "reflective", "indicates_direction": "points one way",
	"measures_length": "measures length", "stable_support": "stands steady", "fulcrum": "works as a pivot",
}
const CONTROLS := [
	["Hover", "See what something is and what a click will do"],
	["Left-click", "Talk to someone · pick something up (or steal it, in red) · use a thing"],
	["Right-click", "Look closer at anyone or anything"],
	["Drag from your pack", "Onto someone, something or the ground: give, use, fill, put down"],
	["T  or  Enter", "Open the box to say or do anything, in your own words"],
	["Tab  (in the box)", "Switch between SAY (words) and DO (actions)"],
	["E", "Act on whatever is nearest"],
	["Esc", "Walk away · close · menu"],
	["WASD / arrows,  Shift", "Walk, run"],
	["I  ·  J", "Pack & gear (hold, wear, treat wounds) · your journal"],
	["Space  ·  F", "Use what's in your right · left hand (hold F to raise a shield)"],
	["X  ·  Q", "Swap hands · throw what's in your right hand"],
	["H", "Talk to the device (it remembers everything you've said)"],
	["Mouse wheel", "Zoom"],
]

var game: Node2D
var root: Control
var hud: Control
var bar: PanelContainer
var card: PanelContainer
var cursor: Node
var sounds: Node
var device: Control # The device from the future (D-50): scripts/ui/device.gd.
var guide: Control # The tutorial's cards, task banner and marker (D-52): scripts/ui/tutorial_guide.gd.
var layers: Control # Toasts, deeds, the reveal card and the pinned goal's marker (D-55): scripts/ui/game_layers.gd.
var modal: PanelContainer
var modal_box: VBoxContainer
var modal_kind := ""
var shade: ColorRect
var curtain: ColorRect
var ui_scale := 1.0
var text_scale := 1.0
var hints: Dictionary = {}
var visited: Dictionary = {} # Vector2i blocks of 4×4 cells walked near, for the journal map.
var visited_run := ""
var _visited_dirty := false
var _visited_clock := 0.0
var round_playing: bool:
	get:
		return bar != null and bar.round_playing


func label(text: String, font_size := 17) -> Label:
	var node := Label.new()
	node.text = text
	node.add_theme_font_size_override("font_size", font_size)
	return node


func button(text: String, call: Callable, variation := "") -> Button:
	var node := Button.new()
	node.text = text
	if not variation.is_empty():
		node.theme_type_variation = variation
	node.pressed.connect(func() -> void: sounds.play("click"))
	node.pressed.connect(call)
	return node


func small(body: Control, text: String) -> Label:
	var node := paragraph(body, text)
	node.theme_type_variation = "Small"
	node.remove_theme_font_size_override("font_size")
	return node


func paragraph(body: Control, text: String) -> Label:
	var node := label(text, 17)
	node.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	node.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(node)
	return node


func build(owner_game: Node2D) -> void:
	game = owner_game
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var settings := ConfigFile.new()
	if settings.load("user://presentation.cfg") == OK:
		ui_scale = clampf(float(settings.get_value("ui", "scale", 1.0)), 0.8, 1.4)
		text_scale = clampf(float(settings.get_value("ui", "text", 1.0)), 0.85, 1.25)
		for key in settings.get_section_keys("hints") if settings.has_section("hints") else []:
			hints[key] = bool(settings.get_value("hints", key))
	sounds = preload("res://scripts/ui/ui_sounds.gd").new()
	add_child(sounds)
	root = Control.new()
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.theme = UITheme.build(text_scale)
	add_child(root)
	hud = preload("res://scripts/ui/hud.gd").new()
	root.add_child(hud)
	hud.build(self, game)
	layers = preload("res://scripts/ui/game_layers.gd").new()
	root.add_child(layers)
	layers.build(self, game)
	device = preload("res://scripts/ui/device.gd").new()
	root.add_child(device)
	device.build(self, game)
	bar = preload("res://scripts/ui/action_bar.gd").new()
	root.add_child(bar)
	bar.build(self, game)

	shade = ColorRect.new()
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.color = Color(0.06, 0.04, 0.02, 0.55)
	root.add_child(shade)
	game.menu = PanelContainer.new()
	game.menu.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	game.menu.grow_horizontal = Control.GROW_DIRECTION_BOTH
	game.menu.grow_vertical = Control.GROW_DIRECTION_BOTH
	game.menu.custom_minimum_size = Vector2(560, 0)
	root.add_child(game.menu)
	var menu_box := VBoxContainer.new()
	menu_box.add_theme_constant_override("separation", 10)
	game.menu.add_child(menu_box)
	var caption := label("A STRANGER OUT OF TIME")
	caption.theme_type_variation = "Caption"
	caption.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	menu_box.add_child(caption)
	var title := label("The City Beyond")
	title.theme_type_variation = "Title"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	menu_box.add_child(title)
	var intro := label("A closed city. An unfamiliar world.\nThe only thing you brought is what you know.", 17)
	intro.add_theme_font_override("font", UITheme.serif(false, true))
	intro.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	menu_box.add_child(intro)
	menu_box.add_child(HSeparator.new())
	var first_time := button("Tutorial (first time)", game._start.bind("normal", "tutorial"))
	menu_box.add_child(first_time)
	menu_box.add_child(button("Begin a journey", game._start.bind("normal")))
	menu_box.add_child(button("Continue last journey", game._resume))
	menu_box.add_child(button("Developer playtest", game._start.bind("developer")))
	game.message = label("Connecting…", 14)
	game.message.theme_type_variation = "Small"
	game.message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game.message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	game.message.custom_minimum_size.x = 500
	menu_box.add_child(game.message)

	var scrim := ColorRect.new() # The world dims behind any open panel (D-55), so the panel reads first.
	scrim.color = Color(0.06, 0.04, 0.02, 0.42)
	scrim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scrim.mouse_filter = Control.MOUSE_FILTER_IGNORE
	scrim.hide()
	root.add_child(scrim)
	modal = PanelContainer.new()
	modal.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	modal.visibility_changed.connect(func() -> void: scrim.visible = modal.visible)
	root.add_child(modal)
	modal_box = VBoxContainer.new()
	modal_box.add_theme_constant_override("separation", 10)
	modal.add_child(modal_box)
	modal.hide()
	card = preload("res://scripts/ui/inspect_card.gd").new()
	root.add_child(card)
	card.build(self, game)

	game.trace_panel = PanelContainer.new()
	game.trace_panel.theme_type_variation = "WoodPanel"
	game.trace_panel.position = Vector2(16, 128)
	game.trace_panel.custom_minimum_size = Vector2(290, 0)
	root.add_child(game.trace_panel)
	var debug_box := VBoxContainer.new()
	game.trace_panel.add_child(debug_box)
	game.trace_text = label("", 13)
	game.trace_text.theme_type_variation = "WoodLabel"
	debug_box.add_child(game.trace_text)
	game.gate_button = button("Open gate (test)", game._toggle_gate)
	debug_box.add_child(game.gate_button)
	debug_box.add_child(button("AI traces  ·  F4", game.open_traces))
	game.trace_panel.hide()

	game.victory_panel = PanelContainer.new()
	game.victory_panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	game.victory_panel.grow_horizontal = Control.GROW_DIRECTION_BOTH
	game.victory_panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	game.victory_panel.custom_minimum_size = Vector2(560, 0)
	root.add_child(game.victory_panel)
	var win_box := VBoxContainer.new()
	win_box.add_theme_constant_override("separation", 10)
	game.victory_panel.add_child(win_box)
	var won := label("Beyond the gate")
	won.theme_type_variation = "Title"
	win_box.add_child(won)
	win_box.add_child(label("You reached the end of this playable area.", 17))
	game.victory_route = label("", 16)
	game.victory_route.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game.victory_route.custom_minimum_size.x = 500
	game.victory_route.add_theme_color_override("font_color", UITheme.ACCENT)
	win_box.add_child(game.victory_route)
	win_box.add_child(button("Return to title", game._back_to_menu))
	game.victory_panel.hide()
	guide = preload("res://scripts/ui/tutorial_guide.gd").new()
	root.add_child(guide) # Above everything else: while a card is up, the world waits.
	guide.build(self, game)

	cursor = preload("res://scripts/world_cursor.gd").new()
	cursor.game = game
	cursor.ui = self
	add_child(cursor)
	curtain = ColorRect.new()
	curtain.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	curtain.color = Color(0, 0, 0, 0)
	curtain.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(curtain)
	get_viewport().size_changed.connect(apply_scale)
	apply_scale()


## UI scale: the whole interface is laid out at 1/scale of the screen, then drawn scaled up.
func apply_scale() -> void:
	var screen := get_viewport_rect().size
	root.scale = Vector2.ONE * ui_scale
	root.position = Vector2.ZERO
	root.size = screen / ui_scale


func save_ui_settings() -> void:
	var settings := ConfigFile.new()
	settings.load("user://presentation.cfg")
	settings.set_value("ui", "scale", ui_scale)
	settings.set_value("ui", "text", text_scale)
	for key in hints:
		settings.set_value("hints", key, hints[key])
	settings.save("user://presentation.cfg")


func hint_seen(key: String) -> bool:
	return hints.get(key, false)


func mark_hint(key: String) -> void:
	if key.is_empty():
		return
	hints[key] = true
	save_ui_settings()


## Fade the whole screen to black (to = 1) or back (to = 0).
func fade(to: float, seconds := 0.6) -> void:
	var tween := create_tween()
	tween.tween_property(curtain, "color:a", to, seconds)
	await tween.finished


func _process(delta: float) -> void:
	shade.visible = game.menu.visible or modal.visible or game.victory_panel.visible
	hud.visible = not game.menu.visible and not game.run_state.is_empty()
	hud.inventory.visible = not bar.visible
	_visited_clock += delta
	if _visited_dirty and _visited_clock > 20.0:
		save_visited()


func notify(text: String) -> void:
	hud.notify(text)


func refresh() -> void:
	hud.refresh()
	if bar.visible and not bar.waiting and not bar.round_playing:
		bar.render_chips()


## Movement stops while a panel is open or the dialogue bar has you typing.
func blocks_movement() -> bool:
	return modal.visible or bar.visible or game.menu.visible or game.victory_panel.visible or guide.is_open()


## Screen pixels covered along the bottom: the dialogue bar when it's open, otherwise the pack.
func bottom_cover() -> float:
	if bar.visible:
		return (bar.size.y + 8.0) * ui_scale
	if hud.visible and hud.inventory.visible:
		return (hud.inventory.size.y + 10.0) * ui_scale
	return 0.0


func pointer_over_ui() -> bool:
	return get_viewport().gui_get_hovered_control() != null


# --- A journey starting and ending ---------------------------------------------------------------

func enter_run(state: Dictionary) -> void:
	close_modal_now()
	bar.own_log.clear()
	bar.last_intent = {}
	bar.hide()
	bar.encounter_view = {}
	bar.encounter_over = false
	card.hide()
	hud._signature = "-"
	hud.visible = true
	load_visited(str(state.get("run_id", "")))
	note_cell(Vector2i(int(state.player.x), int(state.player.y)))
	hud.refresh()
	if state.get("scenario", "village") != "tutorial": # The tutorial teaches these one at a time (D-52).
		hud.show_hint("controls", "Hover over things to see what they are  ·  Left-click to act  ·  Right-click to look closer  ·  T to say or do anything  ·  Drag things from your pack")


func leave_run() -> void:
	save_visited()
	bar.close()
	card.hide()
	close_modal_now()


func note_cell(cell: Vector2i) -> void:
	var centre := Vector2i(cell.x / 4, cell.y / 4)
	for dy in range(-2, 3):
		for dx in range(-2, 3):
			if absi(dx) + absi(dy) <= 3:
				var block := centre + Vector2i(dx, dy)
				if not visited.has(block):
					visited[block] = true
					_visited_dirty = true


func load_visited(run_id: String) -> void:
	visited.clear()
	visited_run = run_id
	var path := "user://maps/%s.json" % run_id
	if run_id.is_empty() or not FileAccess.file_exists(path):
		return
	var saved = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(saved) == TYPE_ARRAY:
		for pair in saved:
			visited[Vector2i(int(pair[0]), int(pair[1]))] = true


func save_visited() -> void:
	_visited_clock = 0.0
	if visited_run.is_empty() or not _visited_dirty:
		return
	_visited_dirty = false
	DirAccess.make_dir_recursive_absolute("user://maps")
	var pairs := []
	for block in visited:
		pairs.append([block.x, block.y])
	var file := FileAccess.open("user://maps/%s.json" % visited_run, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(pairs))


# --- Modal panels -----------------------------------------------------------------------------------

func begin_modal(title: String, kind: String, dims := Vector2(680, 520), scrolling := true) -> VBoxContainer:
	for child in modal_box.get_children():
		modal_box.remove_child(child)
		child.queue_free()
	if not modal.visible:
		sounds.play("open")
	card.hide()
	modal_kind = kind
	modal.offset_left = -dims.x * 0.5
	modal.offset_right = dims.x * 0.5
	modal.offset_top = -dims.y * 0.5
	modal.offset_bottom = dims.y * 0.5
	modal.show()
	var heading := HBoxContainer.new()
	modal_box.add_child(heading)
	var title_label := label(title)
	title_label.theme_type_variation = "Heading"
	title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(title_label)
	var close := button("✕", close_modal, "Quiet")
	close.tooltip_text = "Close  (Esc)"
	close.add_theme_font_size_override("font_size", 20)
	heading.add_child(close)
	var body := VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 10)
	if scrolling:
		var scroll := ScrollContainer.new()
		scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
		scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
		modal_box.add_child(scroll)
		scroll.add_child(body)
	else:
		modal_box.add_child(body)
	return body


func close_modal() -> void:
	if game.request_busy or modal_kind == "death":
		return
	if modal.visible:
		sounds.play("close")
	if modal_kind == "journal":
		save_visited()
	modal.hide()
	modal_kind = ""


## Close whatever is open, without the side effects of the player closing it.
func close_modal_now() -> void:
	modal.hide()
	modal_kind = ""


func open_menu(page := "main") -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	match page:
		"controls":
			var body := begin_modal("Controls", "menu", Vector2(640, 520))
			var grid := GridContainer.new()
			grid.columns = 2
			grid.add_theme_constant_override("h_separation", 18)
			grid.add_theme_constant_override("v_separation", 8)
			body.add_child(grid)
			for pair in CONTROLS:
				var key := label(pair[0], 16)
				key.add_theme_font_override("font", UITheme.serif(true))
				key.add_theme_color_override("font_color", UITheme.ACCENT)
				grid.add_child(key)
				var does := label(pair[1], 16)
				does.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
				does.custom_minimum_size.x = 380
				grid.add_child(does)
			paragraph(body, "There are no command words: whatever you type, the game works out whether you are speaking, doing something, or both.")
			body.add_child(button("Back", open_menu.bind("main")))
		"settings":
			var body := begin_modal("Settings", "menu", Vector2(560, 540))
			_slider(body, "Interface size", 0.8, 1.4, 0.05, ui_scale, func(value: float) -> void:
				ui_scale = value
				apply_scale()
				save_ui_settings())
			paragraph(body, "Text size")
			var sizes := HBoxContainer.new()
			sizes.add_theme_constant_override("separation", 6)
			body.add_child(sizes)
			var group := ButtonGroup.new()
			for pair in [["Small", 0.9], ["Normal", 1.0], ["Large", 1.15]]:
				var choice := button(pair[0], func() -> void:
					text_scale = pair[1]
					root.theme = UITheme.build(text_scale)
					save_ui_settings(), "Chip")
				choice.toggle_mode = true
				choice.button_group = group
				choice.button_pressed = is_equal_approx(text_scale, pair[1])
				sizes.add_child(choice)
			_slider(body, "Camera distance", 0.75, 1.25, 0.05, game.camera_zoom, func(value: float) -> void:
				game.camera_zoom = value
				game._save_settings())
			_slider(body, "Sound volume", 0.0, 1.0, 0.05, game.sound_volume, func(value: float) -> void:
				game.sound_volume = value
				game._save_settings())
			paragraph(body, "The device")
			var device_modes := HBoxContainer.new()
			device_modes.add_theme_constant_override("separation", 6)
			body.add_child(device_modes)
			var device_group := ButtonGroup.new()
			for pair in [["Speaks up at key moments", "speaks"], ["Only when I ask (H)", "asked"]]:
				var choice := button(pair[0], func() -> void: device.set_mode(pair[1]), "Chip")
				choice.toggle_mode = true
				choice.button_group = device_group
				choice.button_pressed = device.mode == pair[1]
				device_modes.add_child(choice)
			body.add_child(button("Show the first-time hints again", func() -> void:
				hints.clear()
				save_ui_settings()
				notify("Hints will show again."), "Chip"))
			body.add_child(button("Back", open_menu.bind("main")))
		_:
			var body := begin_modal("A moment to breathe", "menu", Vector2(440, 430))
			body.add_child(button("Continue", close_modal))
			body.add_child(button("Journal", open_journal.bind("leads")))
			body.add_child(button("Controls", open_menu.bind("controls")))
			body.add_child(button("Settings", open_menu.bind("settings")))
			body.add_child(button("Rewind to the last calm moment", func() -> void:
				close_modal_now()
				game.rewind()))
			body.add_child(button("Save and return to title", game._back_to_menu))
			var saved := paragraph(body, "Every action and step is saved as you go.")
			saved.theme_type_variation = "Small"


func open_pause() -> void:
	open_menu()


func _slider(body: VBoxContainer, title: String, low: float, high: float, step: float, value: float, changed: Callable) -> void:
	paragraph(body, title)
	var slider := HSlider.new()
	slider.min_value = low
	slider.max_value = high
	slider.step = step
	slider.value = value
	slider.custom_minimum_size.y = 24
	slider.value_changed.connect(changed)
	body.add_child(slider)


func open_journal(tab := "goals") -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	var body := begin_modal("Your journal", "journal", Vector2(900, 590), false)
	var book := preload("res://scripts/ui/journal_book.gd").new()
	body.add_child(book)
	book.build(self, game, tab)
	guide.report("journal")


## A readable thing (the wainwright's notebook, D-52): the book, big, with the world paused.
func open_book(obj: Dictionary) -> void:
	if game.run_state.is_empty() or game.request_busy or obj.get("readable") == null:
		return
	card.hide()
	var body := begin_modal(str(obj.name).capitalize(), "book", Vector2(1060, 660), false)
	var book := preload("res://scripts/ui/book.gd").new()
	body.add_child(book)
	book.build(self, game, str(obj.readable))
	guide.report("book")


## Everything you carry, when there's more than the pack bar shows (I).
const SLOT_WORDS := {"right": "Right hand", "left": "Left hand", "head": "Head", "body": "Body", "arms": "Arms",
	"legs": "Legs", "hands": "Hands", "feet": "Feet", "ammo": "Quiver"}
const BODY_SLOTS := ["head", "body", "arms", "legs", "hands", "feet"]


## Pack & gear (D-49): what you hold and wear, what you carry, and your body's conditions with what treats them.
func open_inventory() -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	var body := begin_modal("Pack & gear", "inventory", Vector2(760, 620))
	guide.report("pack")
	var player: Dictionary = game.run_state.get("player", {})
	var carried: Array[Dictionary] = hud.carried_objects()
	var conditions: Array = player.get("conditions", []) if typeof(player.get("conditions")) == TYPE_ARRAY else []
	if not conditions.is_empty():
		body.add_child(_section("Your body"))
		for index in conditions.size():
			var condition: Dictionary = conditions[index]
			if str(condition.get("kind", "")) == "knocked_out":
				continue
			var row := HBoxContainer.new()
			row.add_theme_constant_override("separation", 8)
			body.add_child(row)
			var words := label(condition_words(condition), 16)
			words.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			words.add_theme_color_override("font_color", UITheme.BAD if _needs_treating(condition) else UITheme.INK_SOFT)
			row.add_child(words)
			if not _needs_treating(condition):
				continue
			var fits := carried.filter(func(o: Dictionary) -> bool: return _treats(o, str(condition.kind)))
			if fits.is_empty():
				row.add_child(label("Nothing to treat it with", 14))
			for remedy in fits.slice(0, 3):
				var rid := str(remedy.id)
				var i := int(index)
				row.add_child(button("Treat with the " + str(remedy.name), func() -> void:
					var result: Dictionary = await game.fight.treat(rid, i)
					notify(str(result.get("text", result.get("reason", ""))))
					open_inventory(), "Chip"))
	body.add_child(_section("Holding and wearing"))
	var worn_ids := {}
	var shown := 0
	for slot in SLOT_WORDS:
		var obj: Dictionary = game.fight.in_hand(player, slot)
		if obj.is_empty():
			continue
		worn_ids[str(obj.id)] = true
		if slot == "left" and str(game.fight.in_hand(player, "right").get("id", "")) == str(obj.id):
			continue # Two hands on one thing: shown once.
		shown += 1
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		body.add_child(row)
		row.add_child(object_icon(obj, 48))
		var words := label("%s: %s\n%s" % [SLOT_WORDS[slot], str(obj.name), gear_words(obj)], 15)
		words.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(words)
		var id := str(obj.id)
		if obj.get("readable") != null: # A book in hand: read it (D-55).
			row.add_child(button("Read", open_book.bind(obj), "Chip"))
		row.add_child(button("Take off" if slot in BODY_SLOTS else "Put away", func() -> void:
			var result: Dictionary = await game.fight.equip(id, "")
			if not result.get("ok", false):
				notify(str(result.get("reason", "")))
			open_inventory(), "Chip"))
	if shown == 0:
		small(body, "Empty-handed. Space and F use what's in your right and left hands; X swaps them.")
	body.add_child(_section("In your pack"))
	var loose := carried.filter(func(o: Dictionary) -> bool: return not worn_ids.has(str(o.id)))
	if loose.is_empty():
		paragraph(body, "Nothing else.\n\nClick a loose thing in the world to pick it up. What might you make with what you find?")
	for obj in loose:
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 8)
		body.add_child(row)
		row.add_child(object_icon(obj, 48))
		var made := "  ·  made by you" if obj.get("created_by") == "player" else ""
		var words := label(str(obj.name).capitalize() + "  ·  " + str(obj.mass_kg) + " kg" + made + "\n" + gear_words(obj), 15)
		words.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(words)
		var id := str(obj.id)
		if obj.get("readable") != null:
			row.add_child(button("Read", open_book.bind(obj), "Chip"))
		for slot in _slots_for(obj):
			var chosen := str(slot)
			var verb := "Wear" if chosen in BODY_SLOTS else "Ready" if chosen == "ammo" else "Right hand" if chosen == "right" else "Left hand"
			row.add_child(button(verb, func() -> void:
				var result: Dictionary = await game.fight.equip(id, chosen)
				if not result.get("ok", false):
					notify(str(result.get("reason", "")))
				elif obj.get("readable") != null and chosen in ["right", "left"]:
					open_book(game.run_state.objects.get(id, obj)) # A book taken in hand opens (D-55).
					return
				open_inventory(), "Chip"))
		row.add_child(button("Use…", func() -> void:
			close_modal()
			bar.open(id), "Chip"))
		row.add_child(button("Put down", game._quick_action.bind("drop", id), "Chip"))


func _section(text: String) -> Label:
	var node := label(text, 19)
	node.add_theme_font_override("font", UITheme.serif(true))
	node.add_theme_color_override("font_color", UITheme.INK)
	return node


## Where a thing can go: worn things where they cover, ammunition in the quiver, anything else in a hand.
func _slots_for(obj: Dictionary) -> Array:
	var record = obj.get("gear")
	if typeof(record) == TYPE_DICTIONARY:
		match str(record.get("kind", "")):
			"armour", "clothing":
				var covers: Array = record.get("covers", [])
				return covers.filter(func(c) -> bool: return c in BODY_SLOTS).slice(0, 1)
			"ammo":
				return ["ammo"]
			"remedy":
				return []
	return ["right", "left"]


## How a thing strikes someone who handles it, in plain words (numbers only in developer mode).
func gear_words(obj: Dictionary) -> String:
	var record = obj.get("gear")
	if typeof(record) != TYPE_DICTIONARY:
		return ""
	var table: Dictionary = game.fight.table
	var kind := str(record.get("kind", ""))
	var cls := str(record.get("class", ""))
	if kind == "weapon" and table.get("weapons", {}).has(cls):
		var spec: Dictionary = table.weapons[cls]
		var base := float(spec.get("base", 0))
		var level := "Deadly" if base >= 45 else "Dangerous" if base >= 28 else "Painful" if base >= 12 else "Feeble"
		var how: String = {"cut": "cuts", "pierce": "stabs", "blunt": "clubs", "burn": "burns"}.get(str(spec.type), "hits")
		var reach := "shoots far" if spec.has("range") else "reaches far" if float(spec.reach) >= 2.2 else "close work"
		var dev := "  [%s: %d, reach %.1f, wind-up %d ms]" % [cls, int(base), float(spec.reach), int(spec.windup_ms)] \
			if game.run_state.get("mode", "") == "developer" else ""
		return "%s %s: %s, %s, %s.%s" % [level, spec.name, how, reach, "two hands" if int(spec.hands) == 2 else "one hand", dev]
	if kind in ["armour", "clothing"] and table.get("armour", {}).has(cls):
		var spec: Dictionary = table.armour[cls]
		var cuts := "stops cuts well" if float(spec.cut) >= 0.8 else "turns some cuts" if float(spec.cut) >= 0.35 else "little against a blade"
		return "%s: %s; %s." % [str(spec.name).capitalize(), cuts, "blunt blows still get through" if float(spec.blunt) < 0.4 else "softens blows"]
	if kind == "shield":
		return "A shield: hold its key to raise it against blows from the front."
	if kind == "remedy" and table.get("remedies", {}).has(cls):
		return "Treats %s." % ", ".join(PackedStringArray(table.remedies[cls].treats.keys()))
	if kind == "ammo":
		return "%d left." % int(obj.get("count", 1))
	return ""


func condition_words(condition: Dictionary) -> String:
	var area: String = {"arm": "arm", "leg": "leg", "head": "head", "neck": "neck", "heart": "chest", "torso": "side"}.get(str(condition.get("area", "torso")), "side")
	var treated := int(condition.get("treated", 0))
	match str(condition.kind):
		"bleeding":
			if not _needs_treating(condition):
				return "A cut on your %s, bound (%s)." % [area, str(condition.get("treated_with", "treated"))]
			return ("A deep cut on your %s is bleeding badly." if condition.get("heavy", false) else "A cut on your %s is bleeding.") % area \
				+ (" It's only slowed." if treated > 0 else "")
		"burn":
			return "A burn on your %s%s." % [area, ", dressed" if treated > 0 else " (it will fester if left)"]
		"broken":
			return "Your %s is broken%s." % [area, ", splinted" if treated >= 2 else ": it can't take any weight or grip"]
		"infection":
			return "The wound on your %s is festering%s." % [area, ", poulticed" if treated > 0 else ": it's making you ill"]
	return str(condition.kind)


func _needs_treating(condition: Dictionary) -> bool:
	var treated := int(condition.get("treated", 0))
	match str(condition.get("kind", "")):
		"bleeding":
			return not (treated >= 3 or treated == 2 or (treated >= 1 and not condition.get("heavy", false)))
		"burn", "infection", "broken":
			return treated == 0
	return false


func _treats(obj: Dictionary, kind: String) -> bool:
	var record = obj.get("gear")
	if typeof(record) != TYPE_DICTIONARY or str(record.get("kind", "")) != "remedy":
		return false
	var remedy: Dictionary = game.fight.table.get("remedies", {}).get(str(record.get("class", "")), {})
	return remedy.get("treats", {}).has(kind)


func open_bag() -> void:
	open_inventory()


func inspect(id: String) -> void:
	card.show_for(id)


# --- Pointing, clicking and dragging -----------------------------------------------------------

## A left click on something in your pack: point at it in the dialogue bar.
func item_clicked(id: String) -> void:
	var obj: Dictionary = game.run_state.get("objects", {}).get(id, {})
	if obj.get("readable") != null and not bar.visible:
		open_book(obj) # A book is for reading (D-52).
		return
	if bar.visible:
		bar.add_reference(id)
	else:
		bar.open(id)


## What letting go of a dragged item here would write, e.g. "Give the gourd to Hessa".
func drop_phrase(item_id: String, over: Dictionary) -> String:
	var item: Dictionary = game.run_state.get("objects", {}).get(item_id, {})
	var thing := "the " + str(item.get("name", "thing"))
	if over.is_empty():
		return "Put down " + thing
	if str(over.id) == item_id:
		return ""
	if over.kind == "person":
		return "Give %s to %s" % [thing, over.name]
	var onto: Dictionary = game.run_state.get("objects", {}).get(str(over.id), {})
	if float(item.get("capacity_l", 0)) > 0 and "water_source" in onto.get("capabilities", []):
		return "Fill %s at the %s" % [thing, onto.name]
	return "Use %s on the %s" % [thing, over.name]


func drop_on_item(item_id: String, onto_id: String) -> void:
	var a: Dictionary = game.run_state.objects.get(item_id, {})
	var b: Dictionary = game.run_state.objects.get(onto_id, {})
	if a.is_empty() or b.is_empty():
		return
	_write_line("use the %s with the %s" % [a.name, b.name], "", [item_id, onto_id])


func drop_on_world(item_id: String) -> void:
	var over: Dictionary = cursor.pick(game.get_global_mouse_position()) if not pointer_over_ui() else {}
	if over.is_empty():
		game._quick_action("drop", item_id)
		return
	if not over.get("reachable", true):
		notify("That's too far away. Walk closer first.")
		return
	var phrase := drop_phrase(item_id, over)
	if phrase.is_empty():
		return
	phrase = phrase.left(1).to_lower() + phrase.substr(1)
	if over.kind == "person":
		_write_line(phrase, str(over.id), [item_id])
	else:
		_write_line(phrase, "", [item_id, str(over.id)])


## Fill the dialogue bar's line for the player to check and send (Enter).
func _write_line(text: String, person: String, refs: Array) -> void:
	bar.open(person, "", {}, "do") # Dragging something onto someone or something is a deed.
	for id in refs:
		if str(id) not in bar.selected:
			bar.selected.append(str(id))
	bar.line.text = text + " "
	bar.line.caret_column = bar.line.text.length()
	bar.render_chips()
	hud.show_hint("drag", "Check the words, change anything you like, then press Enter.")


# --- Compatibility with the tools and older call sites ----------------------------------------

func open_encounter(target := "", prefill := "", playing: Dictionary = {}) -> void:
	bar.open(target, prefill, playing)


func open_talk(id: String, prefill := "") -> void:
	bar.open(id, prefill)


func open_try(prefill := "") -> void:
	if game.run_state.is_empty() or game.request_busy or not game.gameplay_active:
		return
	bar.open("", prefill)


func encounter_ended(playing: Dictionary = {}) -> void:
	bar.ended(playing)


# --- Shared wording -----------------------------------------------------------------------------

func npc_record(id: String) -> Dictionary:
	for npc in game.run_state.get("npcs", []):
		if npc.id == id:
			return npc
	return {}


func open_leads() -> PackedStringArray:
	var leads := PackedStringArray()
	var seen := {}
	for claim in game.run_state.get("learned", []):
		var lead := str(claim.get("lead", "")) if claim.get("lead") != null else ""
		if lead.is_empty() or seen.has(lead):
			continue
		seen[lead] = true
		if not _lead_done(claim):
			leads.append(lead)
	return leads


## Whether what a lead points to has happened: a deal done, a loan returned, a person met.
func _lead_done(claim: Dictionary) -> bool:
	if claim.has("fulfilled") or claim.has("gift") or claim.has("trade"):
		return true
	if claim.has("offer"):
		return str(game.run_state.get("agreements", {}).get(str(claim.offer), {}).get("status", "")) == "fulfilled"
	if claim.has("lend"):
		var thing: Dictionary = game.run_state.get("objects", {}).get(str(claim.lend), {})
		return thing.get("holder_id") == claim.npc_id or thing.get("lent_to") != "player"
	if claim.has("refer"):
		var their_mind = npc_record(str(claim.refer)).get("mind")
		return typeof(their_mind) == TYPE_DICTIONARY and their_mind.get("met", false)
	return false


func chip_note(obj: Dictionary) -> String:
	if obj.get("person", false):
		return "" if obj.alive else "  (dead)"
	if obj.holder_id == "player":
		return ""
	var owner: String = game.owner_name(obj)
	if obj.get("lent_to") == "player":
		return "  (lent)"
	return "  (%s's)" % owner if not owner.is_empty() and owner != "you" else ""


func object_icon(obj: Dictionary, edge := 64) -> TextureRect:
	var icon := TextureRect.new()
	icon.texture = game.texture_for(obj)
	icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	icon.custom_minimum_size = Vector2(edge, edge)
	icon.set_meta("object_id", str(obj.id))
	if icon.texture == null:
		var waiting := preload("res://scripts/loading_icon.gd").new()
		waiting.name = "Painting"
		waiting.missing = game.sprite_status(obj) in ["failed", "none"]
		icon.add_child(waiting)
	return icon


## Swap "Painting…" for the picture wherever it's shown once it arrives.
func refresh_icons() -> void:
	hud.refresh()
	for holder in [modal_box, bar, card, layers.reveal]:
		for icon in holder.find_children("*", "TextureRect", true, false):
			if icon.has_meta("object_id") and game.run_state.get("objects", {}).has(icon.get_meta("object_id")):
				var obj: Dictionary = game.run_state.objects[icon.get_meta("object_id")]
				icon.texture = game.texture_for(obj)
				var waiting: Node = icon.get_node_or_null("Painting")
				if waiting and icon.texture != null:
					icon.remove_child(waiting)
					waiting.queue_free()
				elif waiting:
					waiting.missing = game.sprite_status(obj) in ["failed", "none"]


func flag_words(flags: Array) -> String:
	var words: PackedStringArray = []
	for flag in flags:
		words.append(str(FLAG_WORDS.get(flag, flag)))
	return ", ".join(words)


func _listing(names: PackedStringArray) -> String:
	if names.size() <= 1:
		return "".join(names)
	return ", ".join(names.slice(0, names.size() - 1)) + " and " + names[names.size() - 1]


func provenance(obj: Dictionary) -> String:
	var objects: Dictionary = game.run_state.objects
	var parts: PackedStringArray = []
	for id in obj.get("components", []):
		parts.append("a " + str(objects[id].name) if objects.has(id) else str(id))
	var tools: PackedStringArray = []
	for id in obj.get("tools_used", []):
		tools.append("the " + str(objects[id].name) if objects.has(id) else str(id))
	var cut_from: bool = obj.get("components", []).size() == 1 and objects.has(obj.components[0]) \
		and objects[obj.components[0]].has("became")
	var text := ("Cut by you from " if cut_from else "Made by you from ") + _listing(parts)
	if not tools.is_empty():
		text += ", using " + _listing(tools)
	return text + ".\nYour words: “" + str(obj.get("created_text", "")) + "”"


func capability_lines(body: Control, obj: Dictionary) -> void:
	var lines: PackedStringArray = []
	for capability in obj.get("known_capabilities", []):
		lines.append("• " + str(capability.text) + str(CAPABILITY_NOTES.get(str(capability.status), "")))
	if not lines.is_empty():
		paragraph(body, "What it might do:\n" + "\n".join(lines))


## The object a make step produced; older journal entries only record "made".
func _crafted(entry: Dictionary):
	if entry.has("crafted"):
		return entry.crafted
	return entry.get("made") if str(entry.get("action", "make")) == "make" else null


func result_title(entry: Dictionary) -> String:
	var category := str(entry.get("category", ""))
	if category != "success":
		return str(OUTCOME_TITLES.get(category, "Result"))
	# Several steps can succeed at once; title the most striking outcome.
	var harm = entry.get("harm")
	if typeof(harm) == TYPE_DICTIONARY:
		return {"killed": "Killed", "wounded": "Wounded", "missed": "You missed"}.get(str(harm.result), "Done")
	if _crafted(entry) != null:
		return str(OUTCOME_TITLES.success)
	if typeof(entry.get("transformed")) == TYPE_DICTIONARY:
		return "It's done"
	var shown = entry.get("demonstration")
	if typeof(shown) == TYPE_DICTIONARY:
		return "You showed it" if shown.works else "It didn't work"
	if typeof(entry.get("give")) == TYPE_DICTIONARY:
		return "Given"
	if typeof(entry.get("install")) == TYPE_DICTIONARY:
		return "It's in place"
	if typeof(entry.get("offer_trade")) == TYPE_DICTIONARY:
		return "You made an offer"
	if typeof(entry.get("fill")) == TYPE_DICTIONARY:
		return "Filled"
	if not entry.get("taken_ids", []).is_empty():
		return "Taken"
	return "Done"


## "a deep cut to the arm" -> "A deep cut to the arm." (String.capitalize() would title-case every word.)
func _sentence(text: String) -> String:
	text = text.strip_edges()
	if text.is_empty():
		return text
	text = text.left(1).to_upper() + text.substr(1)
	return text if text.right(1) in [".", "!", "?"] else text + "."


## What an attempt changed, in plain sentences (everything a committed step did, even if a later one failed).
func result_details(entry: Dictionary) -> PackedStringArray:
	var lines := PackedStringArray()
	for claim in entry.get("property", []):
		var owner := str(npc_record(str(claim.owner_id)).get("name", claim.owner_id))
		lines.append("The %s belongs to %s (%s)." % [claim.name, owner, str(claim.how).replace("_", " ")])
	var harm = entry.get("harm")
	if typeof(harm) == TYPE_DICTIONARY:
		var victim := str(npc_record(str(harm.target_id)).get("name", harm.target_id))
		lines.append({"killed": "%s is dead.", "wounded": "%s is wounded.", "missed": "%s is unhurt."}.get(
			str(harm.result), "%s") % victim + ("" if str(harm.result) == "missed" else " " + _sentence(str(harm.injury))))
		if not harm.get("witnesses", []).is_empty():
			lines.append("Others nearby saw it.")
	var shown = entry.get("demonstration")
	if typeof(shown) == TYPE_DICTIONARY:
		lines.append("What people saw: " + str(shown.observed))
	var given = entry.get("give")
	if typeof(given) == TYPE_DICTIONARY:
		lines.append("%s now has the %s." % [given.recipient_name, " and the ".join(given.names)])
	var placed = entry.get("install")
	if typeof(placed) == TYPE_DICTIONARY:
		lines.append("The %s is up in the %s." % [placed.object_name, placed.into_name])
	var offered = entry.get("offer_trade")
	if typeof(offered) == TYPE_DICTIONARY:
		lines.append("%s will think it over: your %s for their %s. Talk to them to hear their answer." % [
			offered.recipient_name, " and ".join(offered.give_names), " and ".join(offered.want_names)])
	var filled = entry.get("fill")
	if typeof(filled) == TYPE_DICTIONARY and game.run_state.objects.has(filled.container_id):
		var container: Dictionary = game.run_state.objects[filled.container_id]
		lines.append("The %s holds %s of %s litres." % [container.name, container.water_l, container.capacity_l])
	return lines


## The objects worth showing with a picture: made, cut into pieces, taken.
func result_objects(entry: Dictionary) -> Array:
	var ids := []
	var made = _crafted(entry)
	if made != null:
		ids.append(made)
	var transformed = entry.get("transformed")
	if typeof(transformed) == TYPE_DICTIONARY:
		ids.append_array(transformed.get("into", []))
	for id in entry.get("taken_ids", []):
		if not id in ids:
			ids.append(id)
	var seen := {}
	var unique := []
	for id in ids: # Several identical pieces show once.
		var key := str(game.run_state.get("objects", {}).get(id, {}).get("name", id))
		if not seen.has(key):
			seen[key] = true
			unique.append(id)
	return unique


func show_death(reason: String) -> void:
	bar.close()
	var body := begin_modal("You died", "death", Vector2(560, 380))
	for child in modal_box.get_child(0).get_children(): # No "Close" on the death screen.
		if child is Button:
			child.hide()
	paragraph(body, reason)
	paragraph(body, "The people here remembered what you did, and acted on it.")
	body.add_child(button("Try again from before the trouble began", game.rewind))
	body.add_child(button("Start a new journey", func() -> void:
		modal_kind = ""
		game._back_to_menu()))


# --- Developer views -----------------------------------------------------------------------------

## Developer-only view of one judge call: what was sent, what came back, what code changed.
func trace_view(body: Control, trace: Dictionary) -> void:
	if trace.get("kind") in ["talk", "round"] and not trace.has("judge"):
		talk_trace(body, trace)
		return
	var heading := label("DEVELOPER TRACE")
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
	small(body, summary)
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
	var heading := label("DEVELOPER: LAST EXCHANGE")
	heading.theme_type_variation = "Caption"
	body.add_child(heading)
	var reading: Dictionary = call.get("answers", {})
	var level := func(name: String) -> String:
		var value = reading.get(name, {})
		return "-" if typeof(value) != TYPE_DICTIONARY else str(value.get("score", value.get("noul", "-")))
	small(body, "Move: %s (the voice chose %s)\nReading: impression %s · suspicion %s · anger %s · believes %s · threat %s · reason %s\nTrust %+.2f · suspicion %+.2f\nVoice: %s · %s · %d ms%s" % [
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
	var toggle := button("Show " + title.to_lower(), func() -> void: pass, "Quiet")
	toggle.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	toggle.pressed.connect(func() -> void:
		box.visible = not box.visible
		toggle.text = ("Hide " if box.visible else "Show ") + title.to_lower())
	body.add_child(toggle)
	body.add_child(box)


func show_traces(data: Dictionary) -> void:
	var body := begin_modal("AI traces", "traces", Vector2(900, 600))
	var ai: Dictionary = data.get("ai", {})
	paragraph(body, "AI mode: %s  ·  judge %s (%s)  ·  images %s (%s)\nPeople decide with: %s (%s)  ·  voice %s" % [
		ai.get("mode"), "on" if ai.get("judge") else "off", ai.get("judge_model"),
		"on" if ai.get("images") else "off", ai.get("image_model"), _shown(ai.get("decider")),
		_shown(ai.get("decider_model")), _shown(ai.get("voice_model"))])
	var traces: Array = data.get("traces", [])
	if traces.is_empty():
		paragraph(body, "No attempts yet. Press T in the world and describe something to do.")
	for trace in traces:
		var title := label("“" + str(trace.get("text", "")) + "”", 17)
		title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		title.add_theme_color_override("font_color", UITheme.ACCENT)
		body.add_child(title)
		trace_view(body, trace)
		body.add_child(HSeparator.new())
	var thoughts: Array = data.get("minds", [])
	if not thoughts.is_empty():
		var heading := label("PEOPLE'S DECISIONS (newest first)")
		heading.theme_type_variation = "Caption"
		body.add_child(heading)
		for thought in thoughts:
			var call: Dictionary = thought.get("call", {})
			var what := str(thought.get("action", thought.get("result", thought.get("skipped", "-"))))
			small(body, "%s (%s) → %s\n%s · %s · %d ms · $%s%s%s" % [
				str(thought.npc_id).trim_prefix("npc_"), thought.get("why", ""), what, _shown(call.get("provider")),
				_shown(call.get("model")), int(call.get("latency_ms", 0)), _shown(call.get("cost_usd")),
				(" · one request for %d people" % int(thought.get("people_in_request", 1))) if thought.get("shared_request", false) else "",
				("\nFell back from " + str(call.fallback_from)) if call.get("fallback_from") != null else ""])
			reveal(body, "What %s's decider saw" % str(thought.npc_id).trim_prefix("npc_"),
				str(thought.get("situation", "")) + "\n\nOPTIONS AND ANSWERS\n" +
				JSON.stringify({"questions": thought.get("questions", {}), "answers": call.get("answers", {})}, "  "))
			if thought.get("kind") == "talk":
				var spoken: Dictionary = thought.get("voice", {})
				small(body, "You: “%s”\nSaid: “%s”\nVoice: %s · %s · %d ms" % [thought.get("text", ""),
					thought.get("reply", ""), _shown(spoken.get("status")), _shown(spoken.get("model")),
					int(spoken.get("latency_ms", 0))])
				reveal(body, "What the voice was given", JSON.stringify(thought.get("voice_context", {}), "  "))
		body.add_child(HSeparator.new())
	var sprites: Array = data.get("assets", [])
	if not sprites.is_empty():
		var heading := label("SPRITES")
		heading.theme_type_variation = "Caption"
		body.add_child(heading)
		for sprite in sprites:
			var info: Dictionary = sprite.get("call", {})
			small(body, "%s  ·  %s  ·  %s  ·  %d ms%s" % [sprite.get("record", {}).get("name"), sprite.status,
				_shown(info.get("model")), int(info.get("latency_ms", 0)),
				("\nError: " + str(info.error)) if info.get("error") != null else ""])
			if sprite.status in ["failed", "disabled"]:
				body.add_child(button("Retry painting " + str(sprite.object_id), game.retry_sprite.bind(str(sprite.asset_id)), "Chip"))
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
