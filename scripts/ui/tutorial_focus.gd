extends Node2D
## The tutorial's marker in the world (GDD D-52): a pulsing ring, with a small chevron above it, on the thing, person
## or spot the current task is about. The guide moves it (target) and hides it; it only draws.

const GLOW := Color(0.55, 0.85, 0.95)
var pulse := 0.0


func _ready() -> void:
	z_index = 60
	z_as_relative = false


func _process(delta: float) -> void:
	pulse += delta
	queue_redraw()


func _draw() -> void:
	var grow := 4.0 * sin(pulse * 4.0)
	var radius := 24.0 + grow
	draw_arc(Vector2.ZERO, radius, 0.0, TAU, 48, Color(GLOW, 0.9), 3.0, true)
	draw_arc(Vector2.ZERO, radius + 8.0, 0.0, TAU, 48, Color(GLOW, 0.35 + 0.2 * sin(pulse * 4.0)), 2.0, true)
	var lift := -radius - 26.0 + 5.0 * sin(pulse * 3.0)
	var chevron := PackedVector2Array([Vector2(-10, lift - 10), Vector2(10, lift - 10), Vector2(0, lift + 4)])
	draw_colored_polygon(chevron, Color(GLOW, 0.95))
	draw_polyline(chevron + PackedVector2Array([chevron[0]]), Color(0.05, 0.12, 0.16), 1.5, true)
