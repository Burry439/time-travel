extends Node
## The game's screens: the title, the pause menu and its settings and controls, and death.

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
	var first_time: Button = ui.button("Tutorial (first time)", game.start.bind("normal", "tutorial"))
	menu_box.add_child(first_time)
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
