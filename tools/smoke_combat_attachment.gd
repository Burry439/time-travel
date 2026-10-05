extends SceneTree
## Geometric contracts across measured traveler/NPC views and every phase, using free procedural art.
const Actor := preload("res://scripts/painted_actor.gd")
const HeldArt := preload("res://scripts/held_art.gd")
var worst_grip := 0.0
var worst_support := 0.0
var samples := 0


func _initialize() -> void:
	call_deferred("_run")


func check(ok: bool, reason: String) -> bool:
	if not ok:
		push_error("ATTACHMENT SMOKE FAILED: " + reason)
		quit(1)
	return ok


func measure(actor: Node2D, animation: String, hand: String, two_hands: bool) -> bool:
	var profile := {"animation": animation, "type": "cut" if animation == "slash" else "blunt"}
	var kind := "shield" if animation == "bash" else "weapon"
	var texture := HeldArt.fallback(profile, {"gear": {"kind": kind}})
	var layout := HeldArt.layout(texture, animation, kind)
	actor.set_gear({hand: {"texture": texture, "layout": layout, "animation": animation,
		"kind": kind, "length_m": .8, "hands": 2 if two_hands else 1}}, {})
	for facing in actor.views.size():
		actor.attacks.clear()
		actor.play_attack(animation, 300.0, hand, 400.0)
		for frame in 43:
			actor.set_motion(facing, "idle", 0.0, 1.0 / 60.0)
			var sprite: Sprite2D = actor.held_nodes[facing][hand]
			var socket: Node2D = actor.limbs[facing][hand].socket
			var actual := sprite.to_global(sprite.offset + (layout.grip as Vector2))
			worst_grip = maxf(worst_grip, actual.distance_to(socket.global_position))
			samples += 1
			if not check(worst_grip < .1, "%s %s facing %d frame %d lost the grip" % [actor.actor_id, animation, facing, frame]):
				return false
			if two_hands:
				var support: Node2D = actor.limbs[facing].left.socket
				var second := sprite.to_global(sprite.offset + (layout.support as Vector2))
				var error := second.distance_to(support.global_position)
				worst_support = maxf(worst_support, error)
				if not check(error < 1.0, "%s %s facing %d frame %d supporting grip drifted %.2f px"
						% [actor.actor_id, animation, facing, frame, error]):
					return false
	return true


func _run() -> void:
	var actor := Actor.new()
	root.add_child(actor)
	await process_frame
	for id in ["traveler", "hessa", "roderic", "bren", "oren", "mara", "jory", "tomas", "darin", "elin", "kade", "unknown"]:
		actor.actor_id = id
		await process_frame
		for animation in ["thrust", "overhead", "slash", "throw", "pour", "draw_shoot", "spin_release", "bash"]:
			for hand in ["right", "left", "both"]:
				if not measure(actor, animation, "right" if hand == "both" else hand, hand == "both"):
					return
	actor.actor_id = "traveler"
	actor.set_gear({}, {})
	actor.play_attack("punch", 260, "right", 200)
	actor.play_attack("stab", 180, "left", 240)
	actor.set_motion(0, "idle", 0, .05)
	if not check(actor.attacks.size() == 2, "one hand replaced the other"):
		return
	var predicted := float(actor.attacks.right.t)
	actor.attacks.right.key = "predicted:test"
	actor.reconcile_attack({"hand": "right", "started": 0, "lands_at": 260, "recover_until": 460,
		"profile": {"recover_ms": 200}}, 80)
	if not check(float(actor.attacks.right.t) >= predicted, "accepted anticipation restarted"):
		return
	actor.cancel_attack("left")
	actor.set_motion(0, "idle", 0, .13)
	if not check(not actor.attacks.has("left") and actor.attacks.has("right"), "rejection returned the wrong hand to idle"):
		return
	var blank := Image.create_empty(64, 64, false, Image.FORMAT_RGBA8)
	if not check(not HeldArt.layout(ImageTexture.create_from_image(blank), "thrust", "weapon").suitable,
			"empty held art was treated as a valid grip"):
		return
	print("ATTACHMENT SMOKE PASSED: %d samples, max grip %.4f px, support %.4f px, both hands and reconciliation"
		% [samples, worst_grip, worst_support])
	quit(0)
