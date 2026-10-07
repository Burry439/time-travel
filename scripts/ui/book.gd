extends HBoxContainer
## A readable book: the wainwright's notebook (GDD D-52), found in the old wainwright's yard, or the stranger's own
## survival notes (D-72). Chapters and recipes down the left, the page on the right in large type. Advice, not a
## recipe system: every attempt is still judged. "Type it for me" puts the page's suggested words in the dialogue bar,
## to check and send. A page's "facts" are printed from the world's own material facts (the same the judge rules
## by), and a book with "made_chapter" ends with what the stranger has made on this journey.

const UITheme := preload("res://scripts/ui/ui_theme.gd")

var ui: Control
var game: Node2D
var content: Dictionary = {}
var facts: Dictionary = {} # The world's material facts (data/content/materials.json), quoted by pages.
var page: VBoxContainer


func build(owner_ui: Control, owner_game: Node2D, source: String) -> void:
	ui = owner_ui
	game = owner_game
	var file := FileAccess.open("res://data/content/%s.json" % source, FileAccess.READ)
	if file:
		content = JSON.parse_string(file.get_as_text())
	var materials := FileAccess.open("res://data/content/materials.json", FileAccess.READ)
	if materials:
		facts = (JSON.parse_string(materials.get_as_text()) as Dictionary).get("material_facts", {})
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 18)
	var index_scroll := ScrollContainer.new()
	index_scroll.custom_minimum_size = Vector2(290, 0)
	index_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(index_scroll)
	var index := VBoxContainer.new()
	index.add_theme_constant_override("separation", 2)
	index.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	index_scroll.add_child(index)
	index.add_child(_link("About this book", _intro))
	for chapter in content.get("chapters", []):
		var caption := Label.new()
		caption.theme_type_variation = "Caption"
		caption.text = str(chapter.title).to_upper()
		index.add_child(caption)
		for recipe in chapter.get("recipes", []):
			index.add_child(_link(str(recipe.name), _recipe.bind(recipe)))
	if content.get("made_chapter", false):
		var made_caption := Label.new()
		made_caption.theme_type_variation = "Caption"
		made_caption.text = "THINGS YOU'VE MADE"
		index.add_child(made_caption)
		var made := _made_things()
		if made.is_empty():
			var none := Label.new()
			none.text = "Nothing yet."
			none.add_theme_color_override("font_color", UITheme.INK_SOFT)
			index.add_child(none)
		for entry in made:
			index.add_child(_link(str(entry.made_name).capitalize(), _made_page.bind(entry)))
	var page_scroll := ScrollContainer.new()
	page_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(page_scroll)
	page = VBoxContainer.new()
	page.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page.add_theme_constant_override("separation", 14)
	page_scroll.add_child(page)
	_intro()


func _link(text: String, call: Callable) -> Button:
	var link := Button.new()
	link.text = text
	link.flat = true
	link.alignment = HORIZONTAL_ALIGNMENT_LEFT
	link.add_theme_font_size_override("font_size", 17)
	link.add_theme_color_override("font_color", UITheme.INK)
	link.add_theme_color_override("font_hover_color", UITheme.ACCENT)
	link.pressed.connect(call)
	return link


func _clear() -> void:
	for child in page.get_children():
		page.remove_child(child)
		child.queue_free()


func _text(text: String, font_size := 20, colour := UITheme.INK, bold := false, italic := false) -> Label:
	var node := Label.new()
	node.text = text
	node.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	node.custom_minimum_size.x = 620
	node.add_theme_font_size_override("font_size", font_size)
	node.add_theme_color_override("font_color", colour)
	node.add_theme_font_override("font", UITheme.serif(bold, italic))
	page.add_child(node)
	return node


func _intro() -> void:
	_clear()
	_text(str(content.get("title", "The Notebook")), 30, UITheme.ACCENT, true)
	for paragraph in content.get("intro", []):
		_text(str(paragraph))
	_text("Choose a recipe on the left.", 17, UITheme.INK_SOFT, false, true)


func _recipe(recipe: Dictionary) -> void:
	_clear()
	_text(str(recipe.name), 30, UITheme.ACCENT, true)
	_text("You need", 16, UITheme.INK_SOFT, true)
	_text("  ·  ".join(PackedStringArray(recipe.get("need", []))), 20)
	if recipe.get("fire", false):
		_text("You'll need a fire: Mara's forge, or Hessa's cooking fire at the inn.", 17, UITheme.INK_SOFT, false, true)
	_text("How", 16, UITheme.INK_SOFT, true)
	var number := 1
	for step in recipe.get("steps", []):
		_text("%d.  %s" % [number, str(step).replace("{", "").replace("}", "")], 20)
		number += 1
	if recipe.has("facts"):
		_text("How it works here", 16, UITheme.INK_SOFT, true)
		for key in recipe.get("facts", []):
			if facts.has(key):
				_text(str(facts[key]), 18, UITheme.INK, false, true)
	_text("Good for", 16, UITheme.INK_SOFT, true)
	_text(str(recipe.get("good_for", "")).replace("{", "").replace("}", ""), 20)
	_try_saying(str(recipe.say), str(recipe.get("mode", "do")))


## The things this journey has made, oldest first: each with what happened and the words that made it.
func _made_things() -> Array:
	var made := []
	var seen := {}
	for entry in game.run_state.get("journal", []):
		if typeof(entry) != TYPE_DICTIONARY or entry.get("kind") != "craft" or entry.get("crafted") == null:
			continue
		if str(entry.get("category", "")) not in ["success", "partial_success"] or seen.has(entry.crafted):
			continue
		seen[entry.crafted] = true
		made.append(entry)
	return made


func _made_page(entry: Dictionary) -> void:
	_clear()
	_text(str(entry.made_name).capitalize(), 30, UITheme.ACCENT, true)
	_text("What happened", 16, UITheme.INK_SOFT, true)
	_text(str(entry.get("reason", "")), 20)
	_try_saying(str(entry.get("text", "")), "do")


func _try_saying(words: String, mode: String) -> void:
	if words.strip_edges().is_empty():
		return
	_text("Try saying", 16, UITheme.INK_SOFT, true)
	_text("“%s”" % words, 22, UITheme.ACCENT, true, true)
	var row := HBoxContainer.new()
	page.add_child(row)
	row.add_child(ui.button("Type it for me", func() -> void:
		ui.close_modal_now()
		ui.bar.open("", words, {}, mode)))
