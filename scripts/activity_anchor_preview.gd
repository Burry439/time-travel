@tool
extends Node2D
## Editor-only view of the same activity anchors the backend uses.

@export_file("*.json") var routines_file := "res://data/npc_routines.json"
@export var show_labels := true:
	set(value):
		show_labels = value
		queue_redraw()


func _ready() -> void:
	if Engine.is_editor_hint():
		queue_redraw()
	else:
		hide()


func _draw() -> void:
	if not Engine.is_editor_hint():
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(routines_file))
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	for npc_id in parsed:
		var anchors: Array = parsed[npc_id]["anchors"]
		var goal_text := str(parsed[npc_id]["goal"])
		var on_duty := "guard" in goal_text or "watch" in goal_text or "patrol" in goal_text
		var color := Color(0.34, 0.73, 1.0, 0.85) if on_duty else Color(1.0, 0.72, 0.34, 0.85)
		var points := PackedVector2Array()
		for anchor in anchors:
			points.append(Vector2(float(anchor[0]) + 0.5, float(anchor[1]) + 0.5) * 32.0)
		if points.size() > 1:
			for i in points.size():
				draw_line(points[i], points[(i + 1) % points.size()], color.darkened(0.25), 2.0)
		for i in points.size():
			draw_circle(points[i], 6.0, color)
			if show_labels:
				draw_string(ThemeDB.fallback_font, points[i] + Vector2(10, -6),
					"%s · %s" % [str(npc_id).trim_prefix("npc_"), str(anchors[i][2])],
					HORIZONTAL_ALIGNMENT_LEFT, -1, 11, color)
