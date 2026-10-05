extends PanelContainer
## What the game is waiting on, in words (D-70): "Hessa is thinking…", "Loading your journey…". Shown at the top of
## the screen, over the menu and the game, a beat after a request starts (a quick reply never flickers it), with a
## spinner; after a while it says the AI can take a moment. net.gd keeps the list (net.waiting).

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const SHOW_AFTER_MS := 250 # Quick replies come and go unseen.
const SLOW_AFTER_MS := 6000 # Then a word that it's still working.

var net: Node
var label: Label
var spinner: Control
var angle := 0.0
var shown_text := ""


func build(owner_net: Node) -> void:
	net = owner_net
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var box := StyleBoxFlat.new()
	box.bg_color = Color(UITheme.WOOD_DARK, 0.88)
	box.border_color = UITheme.GOLD_DIM
	box.set_border_width_all(1)
	box.set_corner_radius_all(14)
	box.content_margin_left = 12
	box.content_margin_right = 16
	box.content_margin_top = 6
	box.content_margin_bottom = 6
	add_theme_stylebox_override("panel", box)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(row)
	spinner = Control.new()
	spinner.custom_minimum_size = Vector2(18, 18)
	spinner.mouse_filter = Control.MOUSE_FILTER_IGNORE
	spinner.draw.connect(_draw_spinner)
	row.add_child(spinner)
	label = Label.new()
	label.add_theme_color_override("font_color", UITheme.CREAM)
	label.add_theme_font_size_override("font_size", 16)
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(label)
	hide()


func _process(delta: float) -> void:
	var now := Time.get_ticks_msec()
	var newest: Dictionary = {}
	for ticket in net.waiting:
		var entry: Dictionary = net.waiting[ticket]
		if now - int(entry.since) >= SHOW_AFTER_MS and (newest.is_empty() or int(entry.since) > int(newest.since)):
			newest = entry
	if newest.is_empty():
		if visible:
			hide()
		return
	var text := str(newest.label)
	if now - int(newest.since) >= SLOW_AFTER_MS:
		text += "  (still working: the AI can take a moment)"
	if text != shown_text:
		shown_text = text
		label.text = text
		size = Vector2.ZERO
		reset_size()
	_place()
	if not visible:
		show()
	angle += delta * 5.0
	spinner.queue_redraw()


func _place() -> void:
	var view := get_viewport_rect().size
	position = Vector2(roundf((view.x - size.x) * 0.5), 64.0)


func _draw_spinner() -> void:
	var centre := spinner.size * 0.5
	var radius := minf(spinner.size.x, spinner.size.y) * 0.42
	spinner.draw_arc(centre, radius, 0.0, TAU, 24, Color(1, 1, 1, 0.18), 2.5, true)
	spinner.draw_arc(centre, radius, angle, angle + TAU * 0.3, 12, UITheme.GOLD, 2.5, true)
