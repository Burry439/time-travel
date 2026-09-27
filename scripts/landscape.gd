@tool
extends Node2D
## Deterministic ground detail: visible in the editor, never part of simulation state.
const ROADS := [
	[Vector2(1552, 2350), Vector2(1530, 1950), Vector2(1552, 1400), Vector2(1536, 850), Vector2(1552, 285)],
	[Vector2(1080, 1670), Vector2(1260, 1690), Vector2(1540, 1630), Vector2(2010, 1540)],
	[Vector2(560, 840), Vector2(750, 960), Vector2(1170, 940), Vector2(1540, 920)],
	[Vector2(1540, 920), Vector2(1810, 940), Vector2(2090, 920), Vector2(2580, 1020)]
]

func _draw() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 8065
	# A swept, low-contrast forecourt draws attention to Hessa and the entrance.
	var center := Vector2(1130, 1622)
	for ring in range(9, 0, -1):
		var points := PackedVector2Array()
		for n in 65:
			var angle := TAU * n / 64.0
			points.append(center + Vector2(cos(angle) * (260 + ring * 11), sin(angle) * (92 + ring * 8)))
		draw_colored_polygon(points, Color(0.66, 0.57, 0.41, 0.018))
	for road_index in ROADS.size():
		var road := PackedVector2Array(ROADS[road_index])
		var width := 148.0 if road_index == 0 else 91.0
		# Many translucent rounded layers feather into the ground instead of forming a hard ribbon.
		for edge in range(15, 0, -1):
			var stroke := width - 32 + edge * 5
			var tint := Color(0.69, 0.59, 0.39, 0.058)
			draw_polyline(road, tint, stroke, true)
			for point in road:
				draw_circle(point, stroke * 0.5, tint)
		for i in range(road.size() - 1):
			var tangent := (road[i + 1] - road[i]).normalized()
			var normal := Vector2(-tangent.y, tangent.x)
			for speck in 720:
				var point := road[i].lerp(road[i + 1], rng.randf()) + normal * rng.randf_range(-width * 0.48, width * 0.48)
				draw_line(point, point + Vector2(rng.randf_range(1, 6), 1), Color(0.34, 0.29, 0.20, rng.randf_range(0.06, 0.19)), 1)
	for i in 1900:
		var p := Vector2(rng.randf_range(20, 3052), rng.randf_range(320, 2280))
		if abs(p.x - 1545) < 115:
			continue
		var tint := Color(0.29, 0.34, 0.19, rng.randf_range(0.10, 0.28))
		draw_line(p, p + Vector2(-2, -5), tint, 1)
		draw_line(p + Vector2(2, 0), p + Vector2(3, -4), tint, 1)
