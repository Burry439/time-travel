extends SceneTree
## A picture of the gate with its bar (GDD D-42). Needs the backend running; run windowed:
##   Godot --path . --script res://tools/capture_gate.gd
var scene: Node2D


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene._enter_run(created.data, false)
	await process_frame
	scene.gameplay_active = false # Only a picture: no clock, no halt.
	scene.player.position = scene._cell_center(48, 13)
	scene.camera.reset_smoothing()
	await create_timer(1.0).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/gate_barred.png")
	quit(0)
