extends VBoxContainer
## The journal (GDD §3 Journal): tabs for leads, what people said, your attempts, the things you
## made, the map, and every notice this session. A memory aid, never a codex: nothing here is
## anything the stranger couldn't know.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const TABS := [["leads", "Leads"], ["said", "What people said"], ["attempts", "Attempts"],
	["made", "Things made"], ["map", "Map"], ["notices", "Notices"], ["device", "Device"]]

var ui: Control
var game: Node2D
var tab := "leads"
var tab_row: HBoxContainer
var page: Control


func build(owner_ui: Control, owner_game: Node2D, first_tab: String) -> void:
	ui = owner_ui
	game = owner_game
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 10)
	tab_row = HBoxContainer.new()
	tab_row.add_theme_constant_override("separation", 6)
	add_child(tab_row)
	var group := ButtonGroup.new()
	for pair in TABS:
		var button: Button = ui.button(pair[1], show_tab.bind(pair[0]), "Chip")
		button.toggle_mode = true
		button.button_group = group
		button.set_meta("tab", pair[0])
		tab_row.add_child(button)
	show_tab(first_tab)


func show_tab(name: String) -> void:
	tab = name
	for button in tab_row.get_children():
		button.set_pressed_no_signal(button.get_meta("tab") == name)
	if is_instance_valid(page):
		remove_child(page)
		page.queue_free()
	if name == "map":
		var map := preload("res://scripts/ui/journal_map.gd").new()
		map.setup(ui, game)
		page = map
		add_child(page)
		return
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	var body := VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 8)
	scroll.add_child(body)
	page = scroll
	add_child(page)
	match name:
		"leads": _leads(body)
		"said": _said(body)
		"attempts": _attempts(body)
		"made": _made(body)
		"notices": _notices(body)
		"device": _device(body)


func _heading(body: VBoxContainer, text: String) -> void:
	var node := Label.new()
	node.theme_type_variation = "Caption"
	node.text = text
	body.add_child(node)


func _leads(body: VBoxContainer) -> void:
	ui.paragraph(body, "GET INSIDE THE CITY\nYou arrived from the future with only your knowledge. Explore, notice what is available, and consider what you could do with it.")
	var open_leads: PackedStringArray = ui.open_leads()
	var done := PackedStringArray()
	for claim in game.run_state.get("learned", []):
		var lead := str(claim.get("lead", ""))
		if not lead.is_empty() and ui._lead_done(claim) and not lead in done and not lead in open_leads:
			done.append(lead)
	_heading(body, "OPEN LEADS")
	if open_leads.is_empty():
		ui.paragraph(body, "Nothing yet. People may point you somewhere if you talk to them.")
	for lead in open_leads:
		ui.paragraph(body, "• " + lead)
	if not done.is_empty():
		_heading(body, "DONE")
		for lead in done:
			var node: Label = ui.paragraph(body, "✓ " + lead)
			node.modulate.a = 0.55


func _said(body: VBoxContainer) -> void:
	var by_person := {}
	for claim in game.run_state.get("learned", []):
		var who := str(claim.get("name", "?"))
		if not by_person.has(who):
			by_person[who] = PackedStringArray()
		if claim.has("overheard"): # Gossip the stranger overheard between two villagers.
			by_person[who].append("(overheard, to %s) “%s”" % [claim.overheard, claim.said])
		else:
			by_person[who].append("“%s”" % claim.said)
	if by_person.is_empty():
		ui.paragraph(body, "Nobody has told you anything yet.")
	for who in by_person:
		_heading(body, str(who).to_upper())
		for said in by_person[who]:
			ui.paragraph(body, said)


func _attempts(body: VBoxContainer) -> void:
	var history: Array = game.run_state.get("journal", [])
	var shown := 0
	for index in range(history.size() - 1, -1, -1):
		var entry: Dictionary = history[index]
		if shown >= 40:
			break
		if str(entry.get("kind", "")) == "device":
			continue # In its own tab.
		shown += 1
		var line: String = str(entry.get("reason", ""))
		if entry.has("text") and entry.has("category"):
			line = "“%s”  →  %s" % [entry.text, line]
		ui.paragraph(body, "• " + line)
	if shown == 0:
		ui.paragraph(body, "No discoveries recorded yet.")


func _made(body: VBoxContainer) -> void:
	var any := false
	for obj in game.run_state.get("objects", {}).values():
		if obj.get("created_by") != "player":
			continue
		any = true
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		body.add_child(row)
		row.add_child(ui.object_icon(obj, 64))
		var column := VBoxContainer.new()
		column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(column)
		var title := Label.new()
		title.theme_type_variation = "Heading"
		title.add_theme_font_size_override("font_size", 18)
		title.text = str(obj.name).capitalize() + ("" if str(obj.get("condition", "usable")) == "usable" else "  (" + str(obj.condition) + ")")
		column.add_child(title)
		ui.paragraph(column, ui.provenance(obj))
		ui.capability_lines(column, obj)
	if not any:
		ui.paragraph(body, "You haven't made anything yet. What could you make with what's around you?")


## Everything the device has said, and what you asked it (D-50).
func _device(body: VBoxContainer) -> void:
	var lines: Array = game.run_state.get("device_log", [])
	if lines.is_empty():
		ui.paragraph(body, "The device has been quiet. Press H to ask it something.")
	for index in range(lines.size() - 1, -1, -1):
		var line: Dictionary = lines[index]
		if line.has("question"):
			var asked: Label = ui.paragraph(body, "You asked: “%s”" % str(line.question))
			asked.modulate.a = 0.7
		ui.paragraph(body, "◉  " + str(line.get("text", "")))


func _notices(body: VBoxContainer) -> void:
	var history: Array[Dictionary] = ui.hud.history
	if history.is_empty():
		ui.paragraph(body, "No notices yet this session.")
	for index in range(history.size() - 1, -1, -1):
		var node: Label = ui.paragraph(body, "%s   %s" % [history[index].clock, history[index].text])
		node.add_theme_font_size_override("font_size", 15)
