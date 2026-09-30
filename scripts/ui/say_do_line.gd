extends TextEdit
## The dialogue bar's one line (GDD D-57): what you SAY and what you DO, together in one line. Spoken words sit in
## “quotes” and show blue; what you do shows red. Tab (or the SAY / DO switch) changes which you're typing next,
## and the quotes are put in for you, so “Hold still.” lay the poultice on his arm is one turn. A line with no
## quotes at all is wholly one or the other: whichever is chosen (default_mode).

signal submitted
signal mode_changed(mode: String)

const MAX_LENGTH := 500

var default_mode := "say" # What a line without quotes is.
var say_colour := Color("1f5fa8")
var do_colour := Color("b03a1a")
var shown_mode := ""


class Highlighter extends SyntaxHighlighter:
	func _get_line_syntax_highlighting(line_number: int) -> Dictionary:
		var edit = get_text_edit() # The SayDoLine (untyped: its own methods).
		return edit.colours_for(edit.get_line(line_number))


func _init() -> void:
	syntax_highlighter = Highlighter.new()
	wrap_mode = TextEdit.LINE_WRAPPING_NONE
	scroll_fit_content_height = false
	highlight_current_line = false
	caret_blink = true
	context_menu_enabled = false
	text_changed.connect(_on_text_changed)
	caret_changed.connect(_refresh_mode)


static func has_quotes(t: String) -> bool:
	return "“" in t or "”" in t or "\"" in t


## The line in spans [start, end, "say" | "do"]; quote marks belong to the words they enclose.
static func spans(t: String, fallback: String) -> Array:
	if not has_quotes(t):
		return [[0, t.length(), fallback]]
	var out := []
	var inside := false
	var start := 0
	for i in t.length():
		var ch := t[i]
		if not inside and (ch == "“" or ch == "\""):
			if i > start:
				out.append([start, i, "do"])
			start = i
			inside = true
		elif inside and i > start and (ch == "”" or ch == "\""):
			out.append([start, i + 1, "say"])
			start = i + 1
			inside = false
	if start < t.length():
		out.append([start, t.length(), "say" if inside else "do"])
	return out


## Which you're typing at this point in the line.
func mode_at(t: String, column: int) -> String:
	if not has_quotes(t):
		return default_mode
	var inside := false
	for i in mini(column, t.length()):
		var ch := t[i]
		if not inside and (ch == "“" or ch == "\""):
			inside = true
		elif inside and (ch == "”" or ch == "\""):
			inside = false
	return "say" if inside else "do"


func current_mode() -> String:
	return mode_at(text, get_caret_column())


func colours_for(t: String) -> Dictionary:
	var out := {}
	for span in spans(t, default_mode):
		out[span[0]] = {"color": say_colour if span[2] == "say" else do_colour}
	return out


## The player switched to SAY or DO: carry on typing the other kind, putting quotes in or stepping out of them.
func switch_to(target: String) -> void:
	var t := text
	var c := get_caret_column()
	if not has_quotes(t):
		if t.strip_edges().is_empty() or default_mode == target:
			default_mode = target
			repaint()
			return
		default_mode = "do"
		if target == "do": # What's typed so far was spoken: quote it, then carry on with a deed.
			_set_line("“" + t.strip_edges() + "” ")
			return
	if mode_at(t, c) == target:
		return
	if target == "say":
		var lead := " " if c > 0 and t[c - 1] != " " else ""
		t = t.substr(0, c) + lead + "“”" + t.substr(c)
		c += lead.length() + 1
	elif c > 0 and c < t.length() and t[c - 1] in "“\"" and t[c] in "”\"": # Empty quotes: just take them away.
		t = t.substr(0, c - 1) + t.substr(c + 1)
		c -= 1
		if c == t.length(): # Nothing after them: the space put in before them goes too.
			t = t.rstrip(" ")
			c = t.length()
	else:
		if c < t.length() and t[c] in "”\"":
			c += 1 # Step past the closing quote.
		else:
			t = t.substr(0, c) + "”" + t.substr(c)
			c += 1
		if c >= t.length() or t[c] != " ":
			t = t.substr(0, c) + " " + t.substr(c)
		c += 1
	_set_line(t, c)


func _set_line(t: String, column := -1) -> void:
	text = t
	set_caret_line(0)
	set_caret_column(t.length() if column < 0 else column)
	repaint()


## What to send: the words and the mode. Only words: say. Only a deed: do. Both: a deed with the words in quotes.
func payload() -> Dictionary:
	var t := text.strip_edges()
	if not has_quotes(t):
		return {"text": t, "mode": default_mode}
	var said := PackedStringArray()
	var done := PackedStringArray()
	var both := PackedStringArray()
	for span in spans(t, "do"):
		var part := t.substr(span[0], span[1] - span[0]).strip_edges()
		if span[2] == "say":
			part = part.trim_prefix("“").trim_prefix("\"").trim_suffix("”").trim_suffix("\"").strip_edges()
			if not part.is_empty():
				said.append(part)
				both.append("“%s”" % part)
		elif not part.is_empty():
			done.append(part)
			both.append(part)
	if done.is_empty():
		return {"text": " ".join(said), "mode": "say"}
	if said.is_empty():
		return {"text": " ".join(done), "mode": "do"}
	return {"text": " ".join(both), "mode": "do"}


func put(words: String, mode: String) -> void:
	default_mode = "do" if mode == "do" else "say"
	text = words
	set_caret_line(0)
	set_caret_column(words.length())
	repaint()


func _gui_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode in [KEY_ENTER, KEY_KP_ENTER]:
		accept_event()
		if not event.echo:
			submitted.emit()


func _on_text_changed() -> void:
	var t := text
	var tidy := t.replace("\n", " ").replace("\t", " ")
	if tidy.length() > MAX_LENGTH:
		tidy = tidy.left(MAX_LENGTH)
	if tidy != t:
		var c := get_caret_column()
		text = tidy
		set_caret_column(mini(c, tidy.length()))
	repaint()


func repaint() -> void:
	syntax_highlighter.clear_highlighting_cache()
	queue_redraw()
	_refresh_mode()


func _refresh_mode() -> void:
	var now := current_mode()
	add_theme_color_override("caret_color", say_colour if now == "say" else do_colour)
	add_theme_color_override("font_color", say_colour if default_mode == "say" else do_colour)
	if now != shown_mode:
		shown_mode = now
		mode_changed.emit(now)
