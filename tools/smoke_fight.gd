extends SceneTree
## Real-time fights (GDD D-41). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_fight.gd  [-- --capture]
## Hessa comes at the stranger: her blows land on the clock (even with the dialogue bar open), the screen
## edges flash red; Space punches her until she's down and the fight is over.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("FIGHT SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.3).timeout
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png("res://docs/screenshots/" + name + ".png") == OK, "Screenshot failed")


func fight_lines() -> Array:
	return scene.run_state.get("journal", []).filter(func(e) -> bool: return e.get("kind") == "fight")


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene.enter_run(created.data, false)
	await process_frame
	# Pick up the flat stone at the road's start and hold it in the right hand (D-49): a stone in the fist.
	var took: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
		{"verb": "take", "object_id": "stone_b", "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("take")})
	if not check(took.ok, "Could not pick up the stone: " + str(took.get("data"))):
		return
	scene.accept_state(took.data.state)
	var held: Dictionary = await scene.fight.equip("stone_b", "right")
	if not check(held.get("ok", false) and scene.fight.in_hand(scene.run_state.player, "right").get("id") == "stone_b",
			"Could not take the stone in hand: " + str(held)):
		return
	var cells := []
	var here := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	while here.x != 48:
		here.x += signi(48 - here.x)
		cells.append([here.x, here.y])
	for y in (range(here.y - 1, 54, -1) if here.y > 55 else range(here.y + 1, 56)):
		cells.append([48, y])
	for x in range(47, 38, -1):
		cells.append([x, 55])
	for i in range(0, cells.size(), 20):
		var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells.slice(i, i + 20), "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("move")})
		if not check(reply.ok, "Could not walk to the inn"):
			return
		scene.accept_state(reply.data.state)
	scene.predicted_cell = Vector2i(39, 55)
	scene.player.position = scene.cell_center(39, 55)
	scene.camera.reset_smoothing()
	var started: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/dev/fight" % scene.run_state.run_id,
		{"npc_ids": ["npc_hessa_marr"], "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("fight")})
	if not check(started.ok, "Could not start a fight: " + str(started.get("data"))):
		return
	scene.accept_state(started.data.state)
	if not check(scene.in_fight() and not scene.ui.bar.visible, "The fight didn't start (or the bar stayed open)"):
		return
	# She runs in and swings, on the clock: wait (standing still) until a blow lands.
	var waited := 0.0
	while scene.run_state.player.get("health", 100) >= 100 and waited < 12.0:
		await create_timer(0.25).timeout
		waited += 0.25
	if not check(scene.run_state.player.get("health", 100) < 100, "No blow landed in 12 s of standing still"):
		return
	await screenshot("fight_struck")
	# The bar open (typing) doesn't stop the fight: the clock still runs.
	scene.ui.bar.open()
	var clock_before := int(scene.run_state.sim_time_ms)
	await create_timer(1.6).timeout
	if not check(int(scene.run_state.sim_time_ms) > clock_before, "The clock stopped while the bar was open mid-fight"):
		return
	scene.ui.bar.close()
	# Space and F: punch her until she's down (fists against no armour, fixed damage).
	var hessa := scene.get_node("NPCs/npc_hessa_marr") as Node2D
	for attempt in 30:
		if not scene.in_fight() or not scene.run_state.player.get("alive", true):
			break
		var toward: Vector2 = hessa.position - scene.player.position
		scene.facing_row = scene.facing_for(toward.normalized()) if toward.length() > 1.0 else scene.facing_row
		await scene.fight.strike("right" if attempt % 2 == 0 else "left") # Both fists (D-49).
		await create_timer(0.75).timeout
	var her: Dictionary = scene.ui.npc_record("npc_hessa_marr")
	if not check(scene.run_state.player.get("alive", true), "The stranger died to Hessa's fists"):
		return
	if not check(her.get("down", false) and not scene.in_fight(), "Hessa isn't down or the fight didn't end: " + str(fight_lines().slice(-4))):
		return
	if not check(scene.get_node("NPCs/npc_hessa_marr/PaintedActor").dead, "Hessa isn't shown on the ground"):
		return
	if not check((scene.get_node("NPCs/npc_hessa_marr/Nameplate") as Label).text.ends_with("(down)"), "Nameplate doesn't say down"):
		return
	await screenshot("fight_down")
	print("FIGHT SMOKE PASSED: %d fight lines, player health %d" % [fight_lines().size(), int(scene.run_state.player.health)])
	quit(0)
