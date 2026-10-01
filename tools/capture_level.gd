extends SceneTree
## A picture of a level as it starts (GDD D-59), to check its map and people. Needs the backend running:
##   Godot --path . --script res://tools/capture_level.gd -- --level=<level id> [--cards]
## Writes docs/screenshots/level_<id>.png (with --cards, the first card is left up; otherwise it's read).
var scene: Node2D


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var level := "test_room"
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--level="):
			level = arg.trim_prefix("--level=")
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	await scene.start("developer", level)
	await create_timer(1.5).timeout
	if not "--cards" in OS.get_cmdline_user_args():
		for _i in 10:
			if scene.ui.guide.is_open():
				scene.ui.guide._next()
			await create_timer(0.2).timeout
	await create_timer(1.0).timeout
	await RenderingServer.frame_post_draw
	var path := "res://docs/screenshots/level_%s.png" % level
	root.get_texture().get_image().save_png(path)
	print("CAPTURED ", path)
	quit(0)
