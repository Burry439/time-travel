extends Control
## UI stand-in for an object picture that is still being painted: a spinner and "Painting…",
## or "No picture" if painting failed. game_ui.refresh_icons() removes it when the art arrives.
var missing := false
var angle := 0.0


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _process(delta: float) -> void:
	if not missing:
		angle += delta * 4.0
		queue_redraw()


func _draw() -> void:
	var centre := Vector2(size.x * 0.5, size.y * 0.42)
	var radius := minf(size.x, size.y) * 0.22
	var font := ThemeDB.fallback_font
	var caption := "No picture" if missing else "Painting…"
	var font_size := 11 if size.x < 80 else 13
	var width := font.get_string_size(caption, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	if missing:
		draw_arc(centre, radius, 0.0, TAU, 32, Color(0.86, 0.78, 0.55, 0.8), 2.0, true)
	else:
		draw_arc(centre, radius, 0.0, TAU, 32, Color(1, 1, 1, 0.2), 3.0, true)
		draw_arc(centre, radius, angle, angle + TAU * 0.3, 16, Color(0.98, 0.86, 0.55, 0.95), 3.0, true)
	draw_string(font, Vector2((size.x - width) * 0.5, centre.y + radius + font_size + 4), caption,
		HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color(0.95, 0.9, 0.78, 0.9))
