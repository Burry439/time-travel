extends Node2D
## Something flying (D-49): an arrow, a sling stone, a thrown knife or rock. It flies from where it left the hand
## to where it was aimed over its real flight time (the backend decides whether it hits); a pour is a splash.

var from := Vector2.ZERO
var to := Vector2.ZERO
var flight_s := 0.5
var clock := 0.0
var texture: Texture2D
var kind := "arrow" # arrow | stone | thrown | splash
var arc := 18.0


func _ready() -> void:
	position = from
	z_index = 20


func _process(delta: float) -> void:
	clock += delta
	var k := clampf(clock / maxf(flight_s, 0.01), 0.0, 1.0)
	position = from.lerp(to, k) + Vector2(0, -sin(k * PI) * (arc if kind != "arrow" else arc * 0.4))
	rotation = (to - from).angle() if kind == "arrow" else rotation + delta * 12.0
	queue_redraw()
	if k >= 1.0:
		queue_free()


func _draw() -> void:
	if kind == "splash":
		var k := clampf(clock / maxf(flight_s, 0.01), 0.0, 1.0)
		for i in 9:
			var spread := Vector2.from_angle(i * TAU / 9.0) * (6.0 + 22.0 * k)
			draw_circle(spread, 3.0 * (1.0 - k) + 1.0, Color(0.85, 0.92, 1.0, 0.8 * (1.0 - k)))
		return
	if texture != null:
		var size := texture.get_size()
		var scale_to := 22.0 / maxf(size.x, size.y)
		draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE * scale_to)
		draw_texture(texture, -size * 0.5)
		draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
		return
	if kind == "arrow":
		draw_line(Vector2(-11, 0), Vector2(11, 0), Color(0.36, 0.25, 0.14), 2.0, true)
		draw_colored_polygon(PackedVector2Array([Vector2(11, -3), Vector2(16, 0), Vector2(11, 3)]), Color(0.3, 0.3, 0.32))
		draw_line(Vector2(-11, 0), Vector2(-15, -3), Color(0.85, 0.82, 0.75), 1.5)
		draw_line(Vector2(-11, 0), Vector2(-15, 3), Color(0.85, 0.82, 0.75), 1.5)
	else:
		draw_circle(Vector2.ZERO, 3.5, Color(0.45, 0.42, 0.38))
