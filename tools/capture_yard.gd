extends SceneTree
## A picture of the old wainwright's yard (seed 11, D-51). Needs the backend running; run windowed:
##   Godot --path . --script res://tools/capture_yard.gd
var scene: Node2D


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene.enter_run(created.data, false)
	await process_frame
	await create_timer(1.0).timeout
	scene.gameplay_active = false # Only a picture: no clock, no halt.
	scene.run_state.player.x = 80
	scene.run_state.player.y = 59
	scene.predicted_cell = Vector2i(80, 59)
	scene.player.position = scene.cell_center(80, 59)
	scene.camera.reset_smoothing()
	await create_timer(1.5).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/wainwright_yard.png")
	print("player at ", scene.player.position, " camera ", scene.camera.get_screen_center_position(), " limits ",
		[scene.camera.limit_left, scene.camera.limit_top, scene.camera.limit_right, scene.camera.limit_bottom])
	var node := scene.get_node_or_null("M2Objects/yard_iron_bar") as Node2D
	print("yard_iron_bar node ", node, " ", node.global_position if node else null, " visible ",
		node.is_visible_in_tree() if node else null, " player visible ", scene.player.is_visible_in_tree())
	var missing := []
	for id in scene.run_state.objects:
		if str(id).begins_with("yard_") and scene.art.is_placeholder(scene.run_state.objects[id]):
			missing.append(id)
	print("YARD CAPTURED; without art: ", missing)
	quit(0)
