extends SceneTree
const Actor := preload("res://scripts/painted_actor.gd")
const HeldArt := preload("res://scripts/held_art.gd")


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var background := ColorRect.new()
	background.size = Vector2(1280, 720)
	background.color = Color(.38, .36, .29)
	root.add_child(background)
	var art := Image.load_from_file(ProjectSettings.globalize_path("res://docs/screenshots/gear_samples/spear_held.png"))
	var texture := ImageTexture.create_from_image(art.get_region(Actor.solid_rect(art)))
	var layout := HeldArt.layout(texture, "two_hand_thrust", "weapon")
	if "--npcs" in OS.get_cmdline_user_args():
		var people := ["hessa", "roderic", "bren", "oren", "mara", "jory", "tomas", "darin", "elin", "kade"]
		for column in people.size():
			var label := Label.new()
			label.text = people[column]
			label.position = Vector2(30 + column * 125, 15)
			root.add_child(label)
			for row in 4:
				var actor := Actor.new()
				actor.actor_id = people[column]
				actor.position = Vector2(65 + column * 125, 175 + row * 165)
				root.add_child(actor)
				actor.set_gear({"right": {"texture": texture, "layout": layout, "animation": "two_hand_thrust",
					"kind": "weapon", "hands": 2, "length_m": .8}}, {})
				actor.play_attack("two_hand_thrust", 300, "right", 300)
				actor.set_motion(row, "idle", 0, .3)
	else:
		_traveler(texture, layout)
	for _frame in 6:
		await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/combat_npc_grips.png" \
		if "--npcs" in OS.get_cmdline_user_args() else "res://docs/screenshots/combat_grips_contact.png")
	print("COMBAT CAPTURE SAVED")
	quit(0)


func _traveler(texture: Texture2D, layout: Dictionary) -> void:
	for row in 8:
		var actor := Actor.new()
		actor.height_px = 190
		actor.position = Vector2(135 + (row % 4) * 310, 310 + (row / 4) * 320)
		root.add_child(actor)
		actor.set_gear({"right": {"texture": texture, "layout": layout, "animation": "two_hand_thrust",
			"kind": "weapon", "hands": 2, "length_m": 1.6}}, {})
		actor.play_attack("two_hand_thrust", 300, "right", 300)
		actor.set_motion(row, "idle", 0, .3)
