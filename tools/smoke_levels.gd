extends SceneTree
## Any level on any map (GDD D-59). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_levels.gd
## A journey in the hidden test room swaps in its own map (no gate, its own size, collisions made from its data)
## and its two people; the guide shows its own story's cards, and walking to the hearth moves it on. A journey
## in the village afterwards swaps the village back, gate and all.
var scene: Node2D


func _initialize() -> void:
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("LEVELS SMOKE FAILED: " + reason)
		quit(1)
	return condition


## Press Next through whatever cards are up, and wait for the story to hear it.
func read_cards() -> void:
	for _i in 30:
		await create_timer(0.15).timeout
		if scene.ui.guide.is_open():
			scene.ui.guide._next()
		elif not scene.ui.guide.sending:
			await create_timer(0.3).timeout
			if not scene.ui.guide.is_open():
				return


func people() -> int:
	return scene.get_node("NPCs").get_child_count()


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	await scene.start("developer", "test_room")
	await process_frame
	if not check(scene.map_id == "test_room" and scene.has_node("Map/Floor"), "The test room's map wasn't loaded"):
		return
	if not check(not scene.has_node("Map/Gate") and scene.gate_sprite == null, "The village's gate came along"):
		return
	if not check(scene.world_size == Vector2(640, 512) and scene.camera.limit_right >= 640, "The map's size is wrong"):
		return
	var table := scene.get_node_or_null("BuildingCollision/Table/CollisionShape2D") as CollisionShape2D
	if not check(table != null and (table.shape as RectangleShape2D).size == Vector2(96, 64), "No table to bump into"):
		return
	if not check(people() == 2 and scene.ui.guide.steps.size() == 2, "Not the room's people or story"):
		return
	await read_cards()
	var cells := []
	for i in 8:
		cells.append([9 - i, 11 - i] if i < 7 else [3, 4])
	var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
		{"cells": cells, "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("move")})
	if not check(reply.ok, "Couldn't walk to the hearth"):
		return
	scene.accept_state(reply.data.state)
	var tick: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/explore" % scene.run_state.run_id,
		{"elapsed_ms": 500, "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("tick")})
	scene.accept_state(tick.data.state)
	if not check(int(scene.run_state.tutorial.step) == 1, "Walking to the hearth didn't move the story on"):
		return
	scene.ui.close_modal_now()
	await scene.start("developer")
	await process_frame
	if not check(scene.map_id == "village" and scene.has_node("Map/Gate") and scene.gate_sprite != null,
			"The village didn't come back"):
		return
	if not check(people() == 10 and not scene.has_node("Map/Floor"), "The room's pieces stayed behind"):
		return
	print("LEVELS SMOKE PASS: the test room's map, people and story, then the village again")
	quit(0)
