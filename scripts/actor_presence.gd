@tool
extends Node2D
## Grounding stays visible in the editor; idle movement never changes world facts.
@export var radius := 21.0
@export var breathe := false
var clock := 0.0

func _draw() -> void:
	draw_set_transform(Vector2(2, 1), 0, Vector2(1, 0.33))
	draw_circle(Vector2.ZERO, radius, Color(0.12, 0.16, 0.10, 0.23))
	draw_circle(Vector2.ZERO, radius * 0.65, Color(0.10, 0.13, 0.08, 0.16))

func _process(delta: float) -> void:
	if not breathe or Engine.is_editor_hint():
		return
	clock += delta
	var sprite := get_parent().get_node_or_null("Sprite2D") as Sprite2D
	if sprite:
		sprite.position.y = sin(clock * 1.7 + get_parent().position.x) * 0.65
