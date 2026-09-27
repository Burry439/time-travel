extends SceneTree

func _initialize() -> void:
	call_deferred("_capture")

func _capture() -> void:
	var preview: Node2D = load("res://scenes/inn_courtyard_preview.tscn").instantiate()
	root.add_child(preview)
	var traveler := preview.get_node("Traveler")
	var camera: Camera2D = preview.get_node("PreviewCamera")
	camera.position = traveler.position + Vector2(0, -55)
	camera.zoom = Vector2(3.5, 3.5)
	for step in 4:
		traveler.set_motion(3, "walk", 24.0, 0.13)
		await process_frame
		await RenderingServer.frame_post_draw
		var result := root.get_texture().get_image().save_png("res://docs/screenshots/painted-walk-%s.png" % (step + 1))
		if result != OK:
			push_error("Walk frame could not be saved")
			quit(1)
			return
	print("Painted four-view rig: side walk cycle frames captured")
	quit(0)
