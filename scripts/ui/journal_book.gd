extends VBoxContainer
## The journal (GDD §3 Journal, D-55): your goals (pin one to follow it), the people you've met (how each stands
## toward you, and every word you've exchanged), your deeds, the things you made, everything the device said, a
## log of what you tried and what happened, and the map. A memory aid, never a codex: nothing here is anything
## the stranger couldn't know.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const Deeds := preload("res://scripts/ui/deeds.gd")
const TABS := [["goals", "Goals"], ["stories", "Stories"], ["people", "People"], ["deeds", "Deeds"],
	["made", "Things made"], ["device", "Device"], ["log", "Log"], ["map", "Map"]]

var ui: Control
var game: Node2D
var tab := "goals"
var tab_row: HBoxContainer
var page: Control
var open_person := "" # Whose conversation is unfolded on the People page.


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
		if pair[0] == "stories" and _stories() == null:
			continue # A level that runs no storylines (the training levels).
		var button: Button = ui.button(pair[1], show_tab.bind(pair[0]), "Chip")
		button.toggle_mode = true
		button.button_group = group
		button.set_meta("tab", pair[0])
		tab_row.add_child(button)
	show_tab({"leads": "goals", "said": "people", "attempts": "log", "notices": "log"}.get(first_tab, first_tab))


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
		"goals": _goals(body)
		"stories": _stories_page(body)
		"people": _people(body)
		"deeds": _deeds(body)
		"made": _made(body)
		"device": _device(body)
		"log": _log(body)


func _heading(body: VBoxContainer, text: String) -> void:
	var node := Label.new()
	node.theme_type_variation = "Caption"
	node.text = text
	body.add_child(node)


## A card on the page: a face (or a glyph in its place), a bold line, a quieter line under it, and room for a
## button (added with _action, so it sits centred instead of stretching).
func _card(body: VBoxContainer, face: Texture2D, title: String, sub: String, colour := UITheme.INK, glyph := "") -> HBoxContainer:
	var paper := PanelContainer.new()
	paper.theme_type_variation = "InsetPanel"
	body.add_child(paper)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	paper.add_child(row)
	if face:
		row.add_child(UITheme.picture(face, Vector2(52, 52)))
	elif not glyph.is_empty():
		var mark := Label.new()
		mark.text = glyph
		mark.custom_minimum_size = Vector2(52, 52)
		mark.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		mark.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		mark.add_theme_font_size_override("font_size", 28)
		mark.add_theme_color_override("font_color", colour)
		row.add_child(mark)
	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.add_theme_constant_override("separation", 1)
	row.add_child(column)
	row.set_meta("column", column)
	var top := Label.new()
	top.text = title
	top.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	top.add_theme_font_override("font", UITheme.serif(true))
	top.add_theme_font_size_override("font_size", 17)
	top.add_theme_color_override("font_color", colour)
	column.add_child(top)
	if not sub.is_empty():
		var under := Label.new()
		under.text = sub
		under.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		under.add_theme_font_override("font", UITheme.serif(false, true))
		under.add_theme_font_size_override("font_size", 14)
		under.add_theme_color_override("font_color", UITheme.INK_SOFT)
		column.add_child(under)
	return row


func _action(row: HBoxContainer, text: String, call: Callable) -> void:
	var button: Button = ui.button(text, call, "Chip")
	button.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(button)


# --- Goals --------------------------------------------------------------------------------------------------

func _goals(body: VBoxContainer) -> void:
	var goal := Label.new()
	goal.theme_type_variation = "Heading"
	var admitted = game.run_state.get("admitted")
	goal.text = "You've been let in" if typeof(admitted) == TYPE_DICTIONARY else "Get inside the city"
	body.add_child(goal)
	var let_in_by := str(ui.npc_record(str(admitted.get("by", ""))).get("name", "The watch")) \
		if typeof(admitted) == TYPE_DICTIONARY else ""
	var intro: Label = ui.paragraph(body, ("%s has let you in: walk through the gate to the north. What you learned "
		+ "on the way is below.") % let_in_by if not let_in_by.is_empty() else ("The gate to the north is shut to "
		+ "strangers. People here know things, want things and can speak for you, and every lead below came from "
		+ "someone. Pin one to follow it: it stays at the top left, and the person it's about is marked in the world."))
	intro.add_theme_font_size_override("font_size", 15)
	intro.add_theme_color_override("font_color", UITheme.INK_SOFT)
	var open: Array = ui.open_claims()
	var open_names := PackedStringArray()
	if open.is_empty():
		_heading(body, "OPEN LEADS")
		ui.paragraph(body, "Nothing yet. Talk to people: they'll tell you what they know and what they need.")
	var tasks := open.filter(func(c: Dictionary) -> bool: return ui.is_task(c))
	var facts := open.filter(func(c: Dictionary) -> bool: return not ui.is_task(c))
	for part in [[tasks, "ASKED OF YOU, AND PEOPLE TO SEE"], [facts, "WHAT YOU'VE LEARNED"]]:
		if not part[0].is_empty():
			_heading(body, "%s  ·  %d" % [part[1], part[0].size()])
		for index in range(part[0].size() - 1, -1, -1):
			_lead_card(body, part[0][index])
	for claim in open:
		open_names.append(str(claim.lead))
	var done := PackedStringArray()
	var learned: Array = game.run_state.get("learned", [])
	for index in learned.size():
		var lead := str(learned[index].get("lead", ""))
		if not lead.is_empty() and ui.lead_done(index) and not lead in done and not lead in open_names:
			done.append(lead)
	if not done.is_empty():
		_heading(body, "DONE")
		for lead in done:
			var node: Label = ui.paragraph(body, "✓ " + lead)
			node.modulate.a = 0.55


## One open lead as a card: whose face, who told you, and Pin.
func _lead_card(body: VBoxContainer, claim: Dictionary) -> void:
	var lead := str(claim.lead)
	var person: String = ui.layers.lead_person(claim) if not claim.is_empty() else ""
	var pinned: bool = ui.layers.pinned == lead
	var teller := str(claim.get("name", ""))
	var about := str(ui.npc_record(person).get("name", "")) if person != str(claim.get("npc_id", "")) else ""
	var sub := ("%s told you%s." % [teller, "; it's about " + about if not about.is_empty() else ""]) if not teller.is_empty() else ""
	if pinned:
		sub += ("  " if not sub.is_empty() else "") + "Pinned: marked in the world."
	var row := _card(body, ui.bar.portrait_for(person) if not person.is_empty() else null,
		("◆  " if pinned else "") + lead, sub, UITheme.ACCENT if pinned else UITheme.INK)
	_action(row, "Unpin" if pinned else "Pin", func() -> void:
		ui.layers.pin(lead)
		show_tab("goals"))


# --- Stories (D-61) -----------------------------------------------------------------------------------------

## The storylines this level runs, as the backend worked them out (state.view.stories), or null if it runs none.
func _stories() -> Variant:
	var view = game.run_state.get("view")
	return view.get("stories") if typeof(view) == TYPE_DICTIONARY else null


## What's going on in town that you've come into: what you've learned or seen of each, and how it ended.
func _stories_page(body: VBoxContainer) -> void:
	var known = _stories()
	if typeof(known) != TYPE_ARRAY or (known as Array).is_empty():
		ui.paragraph(body, "Nothing yet. People here have troubles of their own; listen, and you'll come into them.")
		return
	ui.paragraph(body, "What's going on in town that you've come into. How it ends is up to you.").add_theme_color_override(
		"font_color", UITheme.INK_SOFT)
	var learned: Array = game.run_state.get("learned", [])
	for story in known:
		var ended := str(story.get("ended", "")) if story.get("ended") != null else ""
		var parts := PackedStringArray()
		for step in story.get("steps", []): # Every step and ending reached, in order, and whose side (D-67).
			var side := ("%s's side: " % str(step.from)) if not str(step.get("from", "")).is_empty() else ""
			parts.append(("✓ " if step.kind == "outcome" else "• ") + side + str(step.text))
		var whose := str(story.get("whose", ""))
		_card(body, ui.bar.portrait_for(whose) if not whose.is_empty() else null, str(story.title), "\n".join(parts),
			UITheme.INK_SOFT if not ended.is_empty() else UITheme.INK)
		for index in story.get("threads", []): # What people have told you about it: yours to follow and pin.
			if int(index) < learned.size():
				_lead_card(body, learned[int(index)])


# --- People -------------------------------------------------------------------------------------------------

func _people(body: VBoxContainer) -> void:
	var known := []
	for npc in game.run_state.get("npcs", []):
		var word := Deeds.standing_word(npc)
		if word != "unknown" or _transcript(str(npc.id)).size() > 0:
			known.append(npc)
	if known.is_empty():
		ui.paragraph(body, "You haven't met anyone yet. Click someone (or walk up and press E) to talk.")
	ui.paragraph(body, "How each person you've met stands toward you, and every word between you.").add_theme_color_override(
		"font_color", UITheme.INK_SOFT)
	for npc in known:
		var id := str(npc.id)
		var word := Deeds.standing_word(npc)
		var told := PackedStringArray()
		for claim in game.run_state.get("learned", []):
			if str(claim.get("npc_id", "")) == id and not str(claim.get("lead", "")).is_empty() and not str(claim.lead) in told:
				told.append(str(claim.lead))
		var row := _card(body, ui.bar.portrait_for(id), "%s  ·  %s" % [npc.name, str(npc.get("role", "")).capitalize()],
			"\n".join(told.slice(-3)))
		var standing := Label.new()
		standing.text = Deeds.word(game.run_state, word) + ("" if npc.get("alive", true) else "  ·  dead")
		standing.add_theme_color_override("font_color", Deeds.STANDING_COLOURS.get(word, UITheme.INK))
		standing.add_theme_font_override("font", UITheme.serif(true, true))
		standing.add_theme_font_size_override("font_size", 15)
		var column: VBoxContainer = row.get_meta("column")
		column.add_child(standing)
		column.move_child(standing, 1)
		var lines := _transcript(id)
		var unfolded := open_person == id
		if not lines.is_empty():
			_action(row, "Hide" if unfolded else "Conversation (%d)" % lines.size(), func() -> void:
				open_person = "" if open_person == id else id
				show_tab("people"))
		if unfolded:
			var talk := VBoxContainer.new()
			talk.add_theme_constant_override("separation", 4)
			var margin := MarginContainer.new()
			margin.add_theme_constant_override("margin_left", 64)
			margin.add_child(talk)
			body.add_child(margin)
			if lines.is_empty():
				ui.paragraph(talk, "You haven't spoken yet.")
			for line in lines:
				var node: Label = ui.paragraph(talk, str(line.text))
				node.add_theme_font_size_override("font_size", 15)
				node.add_theme_color_override("font_color", UITheme.THEIRS if line.theirs else UITheme.INK)


## Every word between the stranger and this person, oldest first, from the journal.
func _transcript(id: String) -> Array:
	var lines := []
	var name := str(ui.npc_record(id).get("name", ""))
	for entry in game.run_state.get("journal", []):
		if str(entry.get("npc_id", "")) != id:
			continue
		match str(entry.get("kind", "")):
			"talk":
				if not str(entry.get("text", "")).is_empty():
					lines.append({"text": "You: “%s”" % entry.text, "theirs": false})
				if not str(entry.get("reply", "")).is_empty():
					lines.append({"text": "%s: “%s”" % [name, entry.reply], "theirs": true})
			"npc":
				lines.append({"text": str(entry.get("reason", "")), "theirs": true})
			"told":
				lines.append({"text": "(%s)" % str(entry.get("reason", "")), "theirs": false})
	return lines


# --- Deeds, things made, the device, the log -----------------------------------------------------------------

func _deeds(body: VBoxContainer) -> void:
	var deeds: Array = Deeds.compute(game.run_state)
	if deeds.is_empty():
		ui.paragraph(body, "No deeds yet. Make something nobody here has seen, help someone, keep your word: people notice.")
	else:
		ui.paragraph(body, "What you've done here that people will remember.").add_theme_color_override("font_color", UITheme.INK_SOFT)
	for index in range(deeds.size() - 1, -1, -1):
		var deed: Dictionary = deeds[index]
		var who := str(deed.get("who", ""))
		_card(body, ui.bar.portrait_for(who) if not who.is_empty() else null, str(deed.title), str(deed.text),
			Color("9a6a12"), "★")


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


## Everything the device has said, and what you asked it (D-50, D-55). H opens it to talk.
func _device(body: VBoxContainer) -> void:
	var lines: Array = game.run_state.get("device_log", [])
	body.add_child(ui.button("Talk to the device (H)", func() -> void:
		ui.close_modal_now()
		ui.device.open_ask(), "Chip"))
	if lines.is_empty():
		ui.paragraph(body, "The device has been quiet.")
	for index in range(lines.size() - 1, -1, -1):
		var line: Dictionary = lines[index]
		if line.has("question"):
			var asked: Label = ui.paragraph(body, "You asked: “%s”" % str(line.question))
			asked.modulate.a = 0.7
		ui.paragraph(body, "◉  " + str(line.get("text", "")))


## What you tried and what happened, and every notice this session, newest first.
func _log(body: VBoxContainer) -> void:
	_heading(body, "WHAT YOU TRIED")
	var history: Array = game.run_state.get("journal", [])
	var shown := 0
	for index in range(history.size() - 1, -1, -1):
		var entry: Dictionary = history[index]
		if shown >= 40:
			break
		if str(entry.get("kind", "")) in ["device", "talk", "npc", "told", "story"]:
			continue # The device, conversations and stories have their own pages.
		shown += 1
		var line: String = str(entry.get("reason", ""))
		if entry.has("text") and entry.has("category"):
			line = "“%s”  →  %s" % [entry.text, line]
		ui.paragraph(body, "• " + line)
	if shown == 0:
		ui.paragraph(body, "Nothing tried yet.")
	var notices: Array[Dictionary] = ui.hud.history
	if not notices.is_empty():
		_heading(body, "NOTICES THIS SESSION")
		for index in range(notices.size() - 1, -1, -1):
			var node: Label = ui.paragraph(body, "%s   %s" % [notices[index].clock, notices[index].text])
			node.add_theme_font_size_override("font_size", 14)
