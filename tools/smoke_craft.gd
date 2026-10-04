extends SceneTree
## Crafting slice smoke test. Needs the backend running with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_craft.gd  [-- --capture]
## Creates a disposable developer run without replacing the player's last-run pointer.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("CRAFT SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await process_frame
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png("res://docs/screenshots/" + name + ".png") == OK, "Screenshot failed")


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and int(health.data.seed_version) >= 4, "Backend missing or outdated; restart it"):
		return
	if not check(str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	scene.ai_status = health.data.ai
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene.enter_run(created.data, false)
	scene.camera_zoom = 1.0
	await process_frame

	# T opens the dialogue bar; its chips list what is within reach of the start: two branches and the cord.
	scene.ui.open_try()
	await process_frame
	if not check(scene.ui.bar.visible and scene.ui.bar.chip_box.get_child_count() > 0, "Dialogue bar did not open"):
		return
	var offered: Array = scene.actions.try_candidates().map(func(o: Dictionary) -> String: return str(o.id))
	if not check("branch_a" in offered and "cord_a" in offered and "bucket_hessa" not in offered,
			"Unexpected items within reach: " + str(offered)):
		return
	scene.ui.bar.line.text = "tie the cord around the branch"
	await screenshot("craft-try-box")
	await scene.actions.act("tie the cord around the branch", "", ["branch_a", "cord_a"])
	var entry: Dictionary = scene.run_state.last_action
	if not check(entry.category == "success" and entry.made != null, "Craft did not succeed: " + str(entry)):
		return
	var made := str(entry.made)
	var obj: Dictionary = scene.run_state.objects[made]
	if not check(obj.holder_id == "player" and obj.components == ["branch_a", "cord_a"], "New object not in bag"):
		return
	if not check(scene.ui.bar.own_log[-1].kind == "result" and typeof(scene.last_trace) == TYPE_DICTIONARY
			and scene.ui.bar.last_intent.get("kind") == "do", "Inline result or developer trace missing"):
		return
	if not check(not scene.get_node("M2Objects/branch_a").visible, "Consumed branch still on the ground"):
		return

	# The painted sprite is fetched from the backend and replaces the placeholder.
	for i in 40:
		if not scene.art.is_placeholder(obj):
			break
		await create_timer(0.25).timeout
	if not check(not scene.art.is_placeholder(obj), "Sprite never arrived"):
		return
	await screenshot("craft-result")
	scene.ui.bar.close()

	# Drop it: a world sprite appears for an object that has no authored scene node.
	await scene.actions.quick_action("drop", made)
	var sprite := scene.get_node_or_null("M2Objects/" + made) as Sprite2D
	if not check(sprite != null and sprite.visible and sprite.texture != null, "Dropped object has no world sprite"):
		return

	# Reload the run from the backend: the object and its history persist.
	var fresh: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/runs/" + str(scene.run_state.run_id))
	scene.enter_run(fresh.data, false)
	await process_frame
	var again: Dictionary = scene.run_state.objects.get(made, {})
	if not check(again.get("created_text") == "tie the cord around the branch" and again.holder_id == null,
			"Object did not persist through reload"):
		return
	if not check(scene.get_node_or_null("M2Objects/" + made) != null, "World sprite not rebuilt after reload"):
		return
	scene.ui.inspect(made)
	await process_frame
	if not check(scene.ui.card.visible, "Inspect card did not open"):
		return
	await screenshot("craft-inspect")
	scene.ui.card.hide()
	await scene.open_traces()
	if not check(scene.ui.modal_kind == "traces", "AI traces panel did not open"):
		return
	await screenshot("craft-traces")
	# A modified authored item must display its new asset, then restore on an earlier save.
	var altered: Dictionary = fresh.data.objects.branch_b.duplicate(true)
	var original: Texture2D = scene.art.texture_for(altered)
	altered["sprite_asset_id"] = obj.sprite_asset_id
	scene.run_state.objects.branch_b = altered
	scene.view.sync()
	var revised: Texture2D = scene.art.texture_for(altered)
	if not check(revised != null and revised != original, "Changed item retained its authored picture"):
		return
	if not check(scene.get_node("M2Objects/branch_b").texture == revised, "World did not display revised art"):
		return
	var restored: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/runs/" + str(scene.run_state.run_id))
	scene.enter_run(restored.data, false)
	if not check(scene.get_node("M2Objects/branch_b").texture == original, "Earlier save did not restore authored art"):
		return
	print("CRAFT SMOKE OK: made ", made, " from ", obj.components)
	quit(0)
