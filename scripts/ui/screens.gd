extends Node
## The game's screens: the title, the pause menu and its settings and controls, death, and Training (D-59).

const UITheme := preload("res://scripts/ui/ui_theme.gd")

var ui: Control # The UI (scripts/game_ui.gd), whose child this is.
var game: Node2D


## The title screen: the game's name, and starting or continuing a journey.
func build_title(root: Control) -> void:
	game.menu = PanelContainer.new()
	game.menu.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	game.menu.grow_horizontal = Control.GROW_DIRECTION_BOTH
	game.menu.grow_vertical = Control.GROW_DIRECTION_BOTH
	game.menu.custom_minimum_size = Vector2(560, 0)
	root.add_child(game.menu)
	var menu_box := VBoxContainer.new()
	menu_box.add_theme_constant_override("separation", 10)
	game.menu.add_child(menu_box)
	var caption: Label = ui.label("A STRANGER OUT OF TIME")
	caption.theme_type_variation = "Caption"
	caption.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	menu_box.add_child(caption)
	var title: Label = ui.label("The City Beyond")
	title.theme_type_variation = "Title"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	menu_box.add_child(title)
	var intro: Label = ui.label("A closed city. An unfamiliar world.\nThe only thing you brought is what you know.", 17)
	intro.add_theme_font_override("font", UITheme.serif(false, true))
	intro.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	menu_box.add_child(intro)
	menu_box.add_child(HSeparator.new())
	menu_box.add_child(ui.button("Training", open_training.bind("basic")))
	menu_box.add_child(ui.button("Begin a journey", game.start.bind("normal")))
	menu_box.add_child(ui.button("Continue last journey", game.resume))
	menu_box.add_child(ui.button("Developer playtest", game.start.bind("developer")))
	game.message = ui.label("Connecting…", 14)
	game.message.theme_type_variation = "Small"
	game.message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game.message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	game.message.custom_minimum_size.x = 500
	menu_box.add_child(game.message)


## Beyond the gate: the end of this playable area, and how the stranger got in (main.show_victory).
func build_victory(root: Control) -> void:
	game.victory_panel = PanelContainer.new()
	game.victory_panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	game.victory_panel.grow_horizontal = Control.GROW_DIRECTION_BOTH
	game.victory_panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	game.victory_panel.custom_minimum_size = Vector2(560, 0)
	root.add_child(game.victory_panel)
	var win_box := VBoxContainer.new()
	win_box.add_theme_constant_override("separation", 10)
	game.victory_panel.add_child(win_box)
	var won: Label = ui.label("Beyond the gate")
	won.theme_type_variation = "Title"
	win_box.add_child(won)
	win_box.add_child(ui.label("You reached the end of this playable area.", 17))
	game.victory_route = ui.label("", 16)
	game.victory_route.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game.victory_route.custom_minimum_size.x = 500
	game.victory_route.add_theme_color_override("font_color", UITheme.ACCENT)
	win_box.add_child(game.victory_route)
	win_box.add_child(ui.button("Return to title", game.back_to_menu))
	game.victory_panel.hide()



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


func open_menu(page := "main") -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	match page:
		"controls":
			var body: VBoxContainer = ui.begin_modal("Controls", "menu", Vector2(640, 520))
			var grid := GridContainer.new()
			grid.columns = 2
			grid.add_theme_constant_override("h_separation", 18)
			grid.add_theme_constant_override("v_separation", 8)
			body.add_child(grid)
			for pair in CONTROLS:
				var key: Label = ui.label(pair[0], 16)
				key.add_theme_font_override("font", ui.UITheme.serif(true))
				key.add_theme_color_override("font_color", ui.UITheme.ACCENT)
				grid.add_child(key)
				var does: Label = ui.label(pair[1], 16)
				does.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
				does.custom_minimum_size.x = 380
				grid.add_child(does)
			ui.paragraph(body, "There are no command words: whatever you type, the game works out whether you are "
				+ "speaking, doing something, or both.")
			body.add_child(ui.button("Back", open_menu.bind("main")))
		"settings":
			var body: VBoxContainer = ui.begin_modal("Settings", "menu", Vector2(560, 540))
			_slider(body, "Interface size", 0.8, 1.4, 0.05, ui.ui_scale, func(value: float) -> void:
				ui.ui_scale = value
				ui.apply_scale()
				ui.save_ui_settings())
			ui.paragraph(body, "Text size")
			var sizes := HBoxContainer.new()
			sizes.add_theme_constant_override("separation", 6)
			body.add_child(sizes)
			var group := ButtonGroup.new()
			for pair in [["Small", 0.9], ["Normal", 1.0], ["Large", 1.15]]:
				var choice: Button = ui.button(pair[0], func() -> void:
					ui.text_scale = pair[1]
					ui.root.theme = ui.UITheme.build(ui.text_scale)
					ui.save_ui_settings(), "Chip")
				choice.toggle_mode = true
				choice.button_group = group
				choice.button_pressed = is_equal_approx(ui.text_scale, pair[1])
				sizes.add_child(choice)
			_slider(body, "Camera distance", 0.75, 1.25, 0.05, game.camera_zoom, func(value: float) -> void:
				game.camera_zoom = value
				game.save_settings())
			_slider(body, "Sound volume", 0.0, 1.0, 0.05, game.sound_volume, func(value: float) -> void:
				game.sound_volume = value
				game.save_settings())
			ui.paragraph(body, "The device")
			var device_modes := HBoxContainer.new()
			device_modes.add_theme_constant_override("separation", 6)
			body.add_child(device_modes)
			var device_group := ButtonGroup.new()
			for pair in [["Speaks up at key moments", "speaks"], ["Only when I ask (H)", "asked"]]:
				var choice: Button = ui.button(pair[0], func() -> void: ui.device.set_mode(pair[1]), "Chip")
				choice.toggle_mode = true
				choice.button_group = device_group
				choice.button_pressed = ui.device.mode == pair[1]
				device_modes.add_child(choice)
			body.add_child(ui.button("Show the first-time hints again", func() -> void:
				ui.hints.clear()
				ui.save_ui_settings()
				ui.notify("Hints will show again."), "Chip"))
			body.add_child(ui.button("Back", open_menu.bind("main")))
		_:
			var body: VBoxContainer = ui.begin_modal("A moment to breathe", "menu", Vector2(440, 430))
			body.add_child(ui.button("Continue", ui.close_modal))
			body.add_child(ui.button("Journal", ui.open_journal.bind("leads")))
			body.add_child(ui.button("Controls", open_menu.bind("controls")))
			body.add_child(ui.button("Settings", open_menu.bind("settings")))
			body.add_child(ui.button("Rewind to the last calm moment", func() -> void:
				ui.close_modal_now()
				game.rewind()))
			body.add_child(ui.button("Save and return to title", game.back_to_menu))
			var saved: Label = ui.paragraph(body, "Every action and step is saved as you go.")
			saved.theme_type_variation = "Small"


func open_pause() -> void:
	open_menu()


func _slider(body: VBoxContainer, title: String, low: float, high: float, step: float, value: float, changed: Callable) -> void:
	ui.paragraph(body, title)
	var slider := HSlider.new()
	slider.min_value = low
	slider.max_value = high
	slider.step = step
	slider.value = value
	slider.custom_minimum_size.y = 24
	slider.value_changed.connect(changed)
	body.add_child(slider)


func show_death(reason: String) -> void:
	ui.bar.close()
	var body: VBoxContainer = ui.begin_modal("You died", "death", Vector2(560, 380))
	for child in ui.modal_box.get_child(0).get_children(): # No "Close" on the death screen.
		if child is Button:
			child.hide()
	ui.paragraph(body, reason)
	ui.paragraph(body, "The people here remembered what you did, and acted on it.")
	body.add_child(ui.button("Try again from before the trouble began", game.rewind))
	body.add_child(ui.button("Start a new journey", func() -> void:
		ui.modal_kind = ""
		game.back_to_menu()))


# --- Training (D-59) ---------------------------------------------------------------------------------------------

var training: Dictionary = {} # The last catalogue from the service: {tracks, levels}.


## The Training screen: each track's levels in order, what each teaches and how long it takes, done marks, and the
## next one suggested. Every level is open. Hidden levels (the developer's own) only in a developer build.
func open_training(track := "basic") -> void:
	var reply: Dictionary = await game.net.api(HTTPClient.METHOD_GET, "/training")
	if not reply.ok:
		game.message.text = "Start the local backend first: tools/run_m0.ps1"
		return
	training = reply.data
	var levels := _shown_levels()
	var body: VBoxContainer = ui.begin_modal("Training", "training", Vector2(780, 620))
	ui.paragraph(body, "Short scenes, each in its own place with its own people. Play them in any order.")
	var tabs := HBoxContainer.new()
	tabs.add_theme_constant_override("separation", 6)
	body.add_child(tabs)
	for each in training.tracks:
		if each.id == "test" and not levels.any(func(level) -> bool: return level.track == "test"):
			continue
		var tab: Button = ui.button(str(each.title), open_training.bind(str(each.id)), "Chip")
		tab.toggle_mode = true
		tab.button_pressed = each.id == track
		tabs.add_child(tab)
	var here := levels.filter(func(level) -> bool: return level.track == track)
	if here.is_empty():
		ui.paragraph(body, "No levels here yet.")
	var suggested := next_level()
	for level in here:
		_level_card(body, level, str(level.id) == suggested)


func _shown_levels() -> Array:
	return training.get("levels", []).filter(func(level) -> bool: return not level.hidden or OS.is_debug_build())


## The level to suggest: the first not done, basics before advanced (after the one just played, if given).
func next_level(after := "") -> String:
	var levels := _shown_levels().filter(func(level) -> bool: return level.track != "test")
	var start := 0
	for i in levels.size():
		if str(levels[i].id) == after:
			start = i + 1
	for i in range(start, levels.size()):
		if not levels[i].done:
			return str(levels[i].id)
	return str(levels[start].id) if start < levels.size() else ""


func _level_card(body: VBoxContainer, level: Dictionary, suggested: bool) -> void:
	var paper := PanelContainer.new()
	paper.theme_type_variation = "InsetPanel"
	body.add_child(paper)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)
	paper.add_child(row)
	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(column)
	var title: Label = ui.label("%s%s" % [str(level.title), "   ·   Next" if suggested else ""], 19)
	title.add_theme_font_override("font", UITheme.serif(true))
	if suggested:
		title.add_theme_color_override("font_color", UITheme.ACCENT)
	column.add_child(title)
	var about: Label = ui.paragraph(column, str(level.blurb))
	about.custom_minimum_size.x = 520
	var facts := "About %d min  ·  %s" % [int(level.minutes), "  ·  ".join(PackedStringArray(level.teaches))]
	var small: Label = ui.paragraph(column, facts)
	small.theme_type_variation = "Small"
	if level.done:
		var done: Label = ui.label("✓ Done" + ("  ·  best %s" % _clock(int(level.best_s)) if level.best_s != null else ""), 15)
		done.add_theme_color_override("font_color", UITheme.ACCENT)
		column.add_child(done)
	var go: Button = ui.button("Play again" if level.done else "Play", play.bind(str(level.id)))
	go.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(go)


func play(level_id: String) -> void:
	ui.close_modal_now()
	game.start("normal", level_id)


func _clock(seconds: int) -> String:
	return "%d:%02d" % [seconds / 60, seconds % 60]


## A training level told to its end: how long it took against how long it should, what was practised, the deeds
## of the journey, a rating for us (D-59: each level is also a lab), and where to go next.
func level_complete() -> void:
	var run_id := str(game.run_state.get("run_id", ""))
	var result: Dictionary = await game.net.api(HTTPClient.METHOD_GET, "/runs/%s/result" % run_id)
	var listing: Dictionary = await game.net.api(HTTPClient.METHOD_GET, "/training")
	if listing.ok:
		training = listing.data
	var settings := ConfigFile.new() # The title stops suggesting Training to someone who has played it.
	settings.load("user://presentation.cfg")
	settings.set_value("tutorial", "done", true)
	settings.save("user://presentation.cfg")
	var level: Dictionary = game.level
	var body: VBoxContainer = ui.begin_modal(str(level.get("title", "Training")) + ": done", "level_complete",
		Vector2(640, 420), false)
	if result.ok and result.data.seconds != null:
		ui.paragraph(body, "You took %s (about %d minutes expected)." % [_clock(int(result.data.seconds)),
			int(level.get("minutes", 5))])
	if not str(level.get("after", "")).is_empty():
		ui.paragraph(body, str(level.after))
	ui.paragraph(body, "You practised: " + ", ".join(PackedStringArray(level.get("teaches", []))).to_lower() + ".")
	var deeds: Array = (game.run_state.get("view", {}) as Dictionary).get("deeds", [])
	if not deeds.is_empty():
		ui.paragraph(body, "Along the way: " + ", ".join(PackedStringArray(deeds.map(func(d) -> String: return str(d.title)))) + ".")
	ui.paragraph(body, "How was it?")
	var ratings := HBoxContainer.new()
	ratings.add_theme_constant_override("separation", 8)
	body.add_child(ratings)
	var comment := LineEdit.new()
	comment.placeholder_text = "Anything that got in the way? (optional)"
	comment.max_length = 500
	var thanks: Label = ui.label("", 15)
	for pair in [["Too easy", "too_easy"], ["About right", "about_right"], ["Confusing", "confusing"]]:
		ratings.add_child(ui.button(pair[0], func() -> void:
			var sent: Dictionary = await game.net.api(HTTPClient.METHOD_POST, "/runs/%s/feedback" % run_id,
				{"rating": pair[1], "comment": comment.text})
			thanks.text = "Thank you: that helps us improve this part of the game." if sent.ok else "Couldn't save that.", "Chip"))
	body.add_child(comment)
	body.add_child(thanks)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	body.add_child(row)
	var following := next_level(str(level.get("id", "")))
	if not following.is_empty():
		row.add_child(ui.button("Next level", play.bind(following)))
	row.add_child(ui.button("Play again", play.bind(str(level.get("id", "")))))
	row.add_child(ui.button("Back to Training", func() -> void:
		ui.close_modal_now()
		await game.back_to_menu()
		open_training(str(level.get("track", "basic")))))
	row.add_child(ui.button("Carry on here", ui.close_modal, "Quiet"))
