extends Node2D
## Drawn where an object's picture is still being painted (a spinning ring),
## or where it couldn't be painted (a small "?" marker). Never a borrowed picture.
var missing := false
var radius := 14.0


func _process(delta: float) -> void:
	if not missing:
		rotation += delta * 4.0


func _draw() -> void:
	if missing:
		draw_circle(Vector2.ZERO, radius, Color(0.94, 0.9, 0.78, 0.9))
		draw_arc(Vector2.ZERO, radius, 0.0, TAU, 32, Color(0.35, 0.3, 0.22, 0.9), 2.0, true)
		draw_string(ThemeDB.fallback_font, Vector2(-5, 7), "?", HORIZONTAL_ALIGNMENT_LEFT, -1, 20,
			Color(0.35, 0.3, 0.22))
		return
	draw_arc(Vector2.ZERO, radius, 0.0, TAU, 32, Color(1, 1, 1, 0.25), 3.0, true)
	draw_arc(Vector2.ZERO, radius, 0.0, TAU * 0.3, 16, Color(0.98, 0.86, 0.55, 0.95), 3.0, true)
