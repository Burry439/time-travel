extends SceneTree
## The stranger's rig in four facings wearing and holding generated gear (D-49), for eyeballing how worn sheets
## and held views sit. Samples live in docs/screenshots/gear_samples/. Run with a window (not headless):
##   Godot --path . --script res://tools/capture_gear.gd
## Saves docs/screenshots/gear_rig.png (and gear_rig_attack.png mid-thrust).

const Actor := preload("res://scripts/painted_actor.gd")


func _initialize() -> void:
	call_deferred("_run")


func _image(name: String) -> Image:
	return Image.load_from_file(ProjectSettings.globalize_path("res://docs/screenshots/gear_samples/%s.png" % name))


func _run() -> void:
	var stage := Node2D.new()
	root.add_child(stage)
	var backdrop := ColorRect.new()
	backdrop.color = Color(0.55, 0.52, 0.42)
	backdrop.size = Vector2(1280, 720)
	stage.add_child(backdrop)
	var spear_image := _image("spear_held")
	var used := Actor.solid_rect(spear_image)
	var spear := ImageTexture.create_from_image(spear_image.get_region(used))
	var actors := []
	for row in 4:
		var actor := Actor.new()
		actor.actor_id = "traveler"
		actor.height_px = 220.0
		actor.position = Vector2(200 + row * 280, 520)
		stage.add_child(actor)
		actor.set_gear({"right": {"texture": spear, "animation": "thrust", "kind": "weapon", "length_m": 1.6}},
			{"body": _image("mail_worn"), "head": _image("helmet_worn")})
		actor.set_motion(row, "idle", 0.0, 0.0)
		actors.append(actor)
	for _i in 6:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/gear_rig.png")
	for actor in actors:
		actor.play_attack("thrust", 300.0)
	for _i in 30: # Into the thrust.
		for row in actors.size():
			actors[row].set_motion(row, "idle", 0.0, 1.0 / 60.0)
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/gear_rig_attack.png")
	print("GEAR CAPTURE SAVED")
	quit(0)
