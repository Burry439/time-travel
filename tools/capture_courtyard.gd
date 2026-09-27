extends SceneTree

func _initialize() -> void:
	call_deferred("_capture")

func _capture() -> void:
	var preview: Node2D = load("res://scenes/inn_courtyard_preview.tscn").instantiate()
	root.add_child(preview)
	await process_frame
	await RenderingServer.frame_post_draw
	var result := root.get_texture().get_image().save_png("res://docs/screenshots/painted-courtyard-preview.png")
	if result != OK:
		push_error("Could not save the painted courtyard preview")
		quit(1)
		return
	print("Painted courtyard preview captured")
	quit(0)
