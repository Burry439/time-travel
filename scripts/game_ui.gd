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
var screens: Node # The title, pause and settings, victory, death: scripts/ui/screens.gd.
var pack: Node # Pack & gear (D-49): scripts/ui/pack.gd.
var dev: Node # Developer views and AI traces: scripts/ui/dev_views.gd.
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
	screens = preload("res://scripts/ui/screens.gd").new()
	pack = preload("res://scripts/ui/pack.gd").new()
	dev = preload("res://scripts/ui/dev_views.gd").new()
	for part: Node in [screens, pack, dev]:
		part.ui = self
		part.game = game
		add_child(part)
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
	screens.build_title(root)

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

	dev.build_panel(root)
	screens.build_victory(root)
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
		hud.show_hint("controls", "Hover over things to see what they are  ·  Left-click to act  ·  "
			+ "Right-click to look closer  ·  T to say or do anything  ·  Drag things from your pack")


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
		game.actions.quick_action("drop", item_id)
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
	bar.line.put(text + " ", "do")
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


## The open leads' claims, oldest first (one per lead).
func open_claims() -> Array:
	var claims := []
	var seen := {}
	for claim in game.run_state.get("learned", []):
		var lead := str(claim.get("lead", "")) if claim.get("lead") != null else ""
		if lead.is_empty() or seen.has(lead):
			continue
		seen[lead] = true
		if not _lead_done(claim):
			claims.append(claim)
	return claims


## A lead that is something to do (a request, a loan to return, someone to go and see), not only a fact.
static func is_task(claim: Dictionary) -> bool:
	return claim.has("offer") or claim.has("lend") or claim.get("refer") != null


## Text cut at a word to fit a small space.
static func shorten(text: String, most: int) -> String:
	if text.length() <= most:
		return text
	var cut := text.left(most)
	return cut.left(maxi(cut.rfind(" "), most - 12)).rstrip(",;:. ") + "…"


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
	var owner: String = game.actions.owner_name(obj)
	if obj.get("lent_to") == "player":
		return "  (lent)"
	return "  (%s's)" % owner if not owner.is_empty() and owner != "you" else ""


func object_icon(obj: Dictionary, edge := 64) -> TextureRect:
	var icon := TextureRect.new()
	icon.texture = game.art.texture_for(obj)
	icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	icon.custom_minimum_size = Vector2(edge, edge)
	icon.set_meta("object_id", str(obj.id))
	if icon.texture == null:
		var waiting := preload("res://scripts/loading_icon.gd").new()
		waiting.name = "Painting"
		waiting.missing = game.art.sprite_status(obj) in ["failed", "none"]
		icon.add_child(waiting)
	return icon


## Swap "Painting…" for the picture wherever it's shown once it arrives.
func refresh_icons() -> void:
	hud.refresh()
	for holder in [modal_box, bar, card, layers.reveal]:
		for icon in holder.find_children("*", "TextureRect", true, false):
			if icon.has_meta("object_id") and game.run_state.get("objects", {}).has(icon.get_meta("object_id")):
				var obj: Dictionary = game.run_state.objects[icon.get_meta("object_id")]
				icon.texture = game.art.texture_for(obj)
				var waiting: Node = icon.get_node_or_null("Painting")
				if waiting and icon.texture != null:
					icon.remove_child(waiting)
					waiting.queue_free()
				elif waiting:
					waiting.missing = game.art.sprite_status(obj) in ["failed", "none"]


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


