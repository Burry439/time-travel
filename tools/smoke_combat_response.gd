extends SceneTree
## Slow replies must not postpone anticipation, collide with movement, or overwrite newer state.
const Net := preload("res://scripts/net.gd")
var scene: Node2D

class SlowNet extends Net:
	var sent: Array[Dictionary] = []
	func post(path: String, body: Dictionary = {}, timeout := 5.0, retry_unavailable := true) -> Dictionary:
		await get_tree().create_timer(.25).timeout
		sent.append({"path": path, "body": body.duplicate(true)})
		return await super.post(path, body, timeout, retry_unavailable)


func _initialize() -> void:
	call_deferred("_run")


func check(ok: bool, reason: String) -> bool:
	if not ok:
		push_error("RESPONSE SMOKE FAILED: " + reason)
		quit(1)
	return ok


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	if not check(reply.ok, "start isolated backend"):
		return
	scene.enter_run(reply.data, false)
	var simulation: Node = scene
	simulation.set_physics_process(false)
	var old_net: Node = scene.net
	var slow := SlowNet.new()
	slow.game = scene
	slow.server = old_net.server
	scene.add_child(slow)
	scene.net = slow
	var old_state: Dictionary = scene.run_state.duplicate(true)
	scene.fight.strike("right")
	if not check(scene.player_visual.attacks.has("right") and slow.sent.is_empty(), "anticipation waited for HTTP"):
		return
	scene.fight.strike("left")
	if not check(scene.player_visual.attacks.size() == 2, "simultaneous hand animation was lost"):
		return
	for _i in 80:
		await create_timer(.025).timeout
		if not scene.fight.busy:
			break
	if not check(slow.sent.size() == 2 and slow.sent[1].body.expected_version > slow.sent[0].body.expected_version,
			"queued commands used stale versions"):
		return
	# The server writes ready_at at contact, not at acceptance. Active swings must retain their recovery.
	scene.fight.sync()
	for hand in ["right", "left"]:
		var swing: Dictionary = scene.run_state.player.swings[hand]
		if not check(scene.fight.readiness(hand) > 0 and scene.fight.local_ready[hand] > Time.get_ticks_msec(),
				"accepted wind-up became ready before contact"):
			return
		if scene.player_visual.attacks.has(hand) and not check(
			is_equal_approx(float(scene.player_visual.attacks[hand].recovery), float(swing.profile.recover_ms) / 1000.0),
			"accepted wind-up lost its recovery timeline"):
			return
	var version := int(scene.run_state.event_seq)
	scene.accept_state(old_state)
	if not check(int(scene.run_state.event_seq) == version, "late state overwrote accepted strikes"):
		return
	scene.run_state.sim_time_ms = int(scene.run_state.player.swings.right.recover_until) - 120
	scene.fight.local_ready.right = Time.get_ticks_msec() + 120
	scene.fight.strike("right")
	if not check(scene.fight.buffers.has("right"), "attack near recovery was not buffered"):
		return
	scene.ui.pack.open()
	await process_frame
	if not check(scene.fight.buffers.is_empty(), "blocking panel retained attack buffer"):
		return
	scene.ui.close_modal_now()
	scene.fight.local_ready.clear()
	scene.run_state.player.ready_at = {} # Deliberately stale readiness, while the server still has recovery.
	scene.run_state.player.swings = {}
	scene.fight.strike("right") # Server recovery rejects it; only a smooth return is shown.
	for _i in 80:
		await create_timer(.025).timeout
		if not scene.fight.busy:
			break
	await process_frame # The command's waiting caller resumes after the lane finishes.
	if not check(scene.player_visual.attacks.get("right", {}).has("cancel_at"), "rejected attack did not reconcile"):
		return
	var other: Dictionary = scene.run_state.duplicate(true)
	other.run_id = "another-journey"
	other.event_seq = version + 100
	scene.accept_state(other)
	if not check(str(scene.run_state.run_id) == str(old_state.run_id), "late reply from another journey was accepted"):
		return
	# Depart while a rejected old command is in flight, then anticipate in a real new journey.
	scene.player_visual.attacks.clear()
	scene.fight.local_ready.clear()
	scene.run_state.player.ready_at = {}
	scene.run_state.player.swings = {}
	scene.fight.strike("right")
	var fresh: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	if not check(fresh.ok, "could not create the second journey"):
		return
	scene.enter_run(fresh.data, false)
	scene.fight.strike("right")
	for _i in 80:
		await create_timer(.025).timeout
		if not scene.fight.busy:
			break
	await process_frame
	if not check(not scene.player_visual.attacks.get("right", {}).has("cancel_at")
			and not scene.run_state.player.get("swings", {}).is_empty(), "old journey's rejection cancelled the new attack"):
		return
	print("RESPONSE SMOKE PASSED: input-frame anticipation with 250 ms delay, ordered hands, stale replies, buffer and rejection")
	quit(0)
