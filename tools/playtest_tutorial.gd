extends SceneTree
## A scripted run of the tutorial's second half with the live models (GDD D-57): the bug bash for "The first
## morning". Needs the backend running live (no AI_MODE=stub):
##   ./tools/run_m0.ps1
##   Godot --path . --script res://tools/playtest_tutorial.gd  [-- --capture]
## The early steps (walking, looking, picking up) are covered by smoke_tutorial; here: talk to Jory, make and put on
## the poultice, Mara bringing Kade (does anyone walk off mid-word?), sword and shield, the bout, telling Kade why
## you're here, the steel file, the fire in front of Kade, Kade's word to the captain and the captain letting you in.
## It reports every step and ends with BLOCKERS and NOTES, like playtest_demo.
const KADE := "npc_kade_east"
const MARA := "npc_mara_venn"
const JORY := "npc_jory_venn"
const RODERIC := "npc_roderic_vale"
var scene: Node2D
var capture := false
var blockers: PackedStringArray = []
var notes: PackedStringArray = []


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func blocker(text: String) -> void:
	blockers.append(text)
	print("  !! BLOCKER: ", text)


func note(text: String) -> void:
	notes.append(text)
	print("  .. note: ", text)


func shot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.5).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/tutorial_live_%s.png" % name)


func step_id() -> String:
	var tutorial = scene.run_state.get("tutorial")
	if typeof(tutorial) != TYPE_DICTIONARY or tutorial.get("done", false):
		return "done"
	return str(scene.ui.guide.steps[int(tutorial.step)].id)


func read_cards() -> void:
	for _i in 40:
		await create_timer(0.15).timeout
		if scene.ui.guide.is_open():
			scene.ui.guide._next()
		elif not scene.ui.guide.sending:
			await create_timer(0.3).timeout
			if not scene.ui.guide.is_open():
				return


func wait_for_step(wanted: String, seconds := 30.0) -> bool:
	var waited := 0.0
	while step_id() != wanted and waited < seconds:
		await create_timer(0.25).timeout
		waited += 0.25
		if scene.ui.guide.is_open():
			await read_cards()
	return step_id() == wanted


func skip() -> void:
	var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/tutorial/skip" % scene.run_state.run_id, {})
	if reply.ok:
		scene._accept_state(reply.data.state)
	await read_cards()


func idle() -> void:
	for i in 100:
		if not scene.request_busy and not scene.movement_sync_active and not scene.sync_error and scene.gameplay_active:
			return
		await create_timer(0.1).timeout


func settle(limit_s := 120.0) -> bool:
	await process_frame
	var waited := 0.0
	while waited < limit_s:
		if not scene.request_busy and not scene.ui.bar.round_playing and not scene.ui.bar.waiting:
			return true
		await create_timer(0.1).timeout
		waited += 0.1
	return false


var blocked := {}


## The same cells the server treats as solid (buildings and obstacles in data/world_geometry.json).
func load_blocked() -> void:
	var geometry: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://data/world_geometry.json"))
	for item in geometry.get("buildings", []) + geometry.get("obstacles", []):
		var c: Array = item.cells
		for x in range(int(c[0]), int(c[0]) + int(c[2])):
			for y in range(int(c[1]), int(c[1]) + int(c[3])):
				blocked[Vector2i(x, y)] = true


## Straight steps (no corner-cutting) around buildings to within a cell of the goal, as the server's own planner.
func path_to(start: Vector2i, goal: Vector2i) -> Array:
	var previous := {start: start}
	var frontier: Array[Vector2i] = [start]
	var reached := Vector2i(-1, -1)
	while not frontier.is_empty():
		var cell: Vector2i = frontier.pop_front()
		if Vector2(cell).distance_to(Vector2(goal)) <= 1.0:
			reached = cell
			break
		for step in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			var next: Vector2i = cell + step
			if previous.has(next) or blocked.has(next) or next.x < 0 or next.x >= 96 or next.y < 9 or next.y >= 72:
				continue
			previous[next] = cell
			frontier.append(next)
	var cells := []
	while reached != Vector2i(-1, -1) and reached != start:
		cells.push_front([reached.x, reached.y])
		reached = previous[reached]
	return cells


func walk_to(cell: Vector2i) -> void:
	if blocked.is_empty():
		load_blocked()
	var here := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	var cells := path_to(here, cell)
	for i in range(0, cells.size(), 20):
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells.slice(i, i + 20), "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("move")})
		if typeof(reply.data) == TYPE_DICTIONARY and reply.data.has("state"):
			scene._accept_state(reply.data.state)
		if not reply.ok:
			note("walk to %s refused: %s" % [cell, JSON.stringify(reply.data).left(140)])
			break
	scene.predicted_cell = Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	scene.player.position = scene._cell_center(scene.predicted_cell.x, scene.predicted_cell.y)
	await create_timer(0.6).timeout
	await idle()


func beside(npc_id: String) -> void:
	var npc: Dictionary = scene.ui.npc_record(npc_id)
	await walk_to(Vector2i(int(npc.x), int(npc.y) + 1))


func bar_line(text: String, mode: String, to := "") -> Array:
	await idle()
	scene.ui.bar.open(to)
	await process_frame
	scene.ui.bar.line.put(text, mode)
	var before: int = scene.run_state.get("journal", []).size()
	scene.ui.bar.submit()
	if not await settle():
		blocker("'%s' never finished" % text.left(40))
	var added: Array = scene.run_state.get("journal", []).slice(before)
	var shown: Array = scene.ui.bar.own_log.filter(func(e) -> bool: return e.get("tone") == "bad")
	if added.is_empty():
		note("nothing happened for '%s': %s" % [text.left(40), shown[-1].text if not shown.is_empty() else "no message"])
	for entry in added:
		var words := str(entry.get("reply", entry.get("reason", "")))
		print("     [%s %s] %s" % [entry.get("kind", ""), entry.get("npc_id", entry.get("category", "")), words.left(170)])
	scene.ui.bar.escape()
	await settle()
	scene.ui.bar.escape()
	await settle()
	scene.ui.bar.close()
	return added


func cell_of(npc_id: String) -> Vector2:
	var npc: Dictionary = scene.ui.npc_record(npc_id)
	return Vector2(float(npc.x), float(npc.y))


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/health")
	if not health.ok or str(health.data.get("ai", {}).get("mode", "")) == "stub":
		push_error("PLAYTEST: start the backend live (not stub): ./tools/run_m0.ps1")
		quit(1)
		return
	scene.ai_status = health.data.ai
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer", "scenario": "tutorial"})
	scene._enter_run(created.data, false)
	await create_timer(1.0).timeout
	print("TUTORIAL PLAYTEST run ", scene.run_state.run_id)
	# The early steps are smoke_tutorial's; here only what they leave in the pack matters.
	for id in ["plantain_a", "flint_a", "grass_a"]:
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
			{"verb": "take", "object_id": id, "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("take")})
		if reply.ok:
			scene._accept_state(reply.data.state)
	for _i in 8:
		if step_id() == "smithy":
			break
		await skip()
	await beside(JORY)
	if not await wait_for_step("talk"):
		blocker("walking to Jory didn't reach Talking: " + step_id())
	print("\n== Talk to Jory")
	await bar_line("Let me see your arm.", "say", JORY)
	print("\n== The poultice")
	if not await wait_for_step("remedy"):
		blocker("talking to Jory didn't move on: " + step_id())
	await bar_line("crush the plantain leaves into a poultice for a burn", "do")
	if not await wait_for_step("treat"):
		blocker("the poultice didn't move on: " + step_id())
	await bar_line("lay the poultice on Jory's burn and bind it", "do", JORY)
	if not await wait_for_step("kade"):
		blocker("treating Jory didn't move on: " + step_id())

	print("\n== Mara brings Kade")
	var told_at := -1.0
	var moved_while_told := 0.0
	var kade_then := Vector2.ZERO
	var waited := 0.0
	while waited < 120.0 and str(scene.run_state.objects.get("practice_sword", {}).get("holder_id", "")) != "player":
		await create_timer(0.5).timeout
		waited += 0.5
		if scene.ui.guide.is_open():
			await read_cards()
		var fired: Array = scene.run_state.tutorial.get("fired", [])
		if told_at < 0.0 and "kade:reply" in fired:
			told_at = waited
			kade_then = cell_of(KADE)
			print("  Mara told Kade after %.1f s; Kade at %s, Mara at %s" % [waited, kade_then, cell_of(MARA)])
		elif told_at >= 0.0 and waited - told_at <= 3.0:
			moved_while_told = maxf(moved_while_told, cell_of(KADE).distance_to(kade_then))
	print("  lent after %.1f s; Kade moved %.1f cells in the 3 s after hearing her; Mara now %.1f cells from you" % [
		waited, moved_while_told, cell_of(MARA).distance_to(Vector2(scene.run_state.player.x, scene.run_state.player.y))])
	if moved_while_told > 0.5:
		blocker("Kade walked off while Mara was still talking to him")
	if str(scene.run_state.objects.get("practice_sword", {}).get("holder_id", "")) != "player":
		blocker("Kade never came and lent the practice sword")
	await shot("kade_arrives")

	print("\n== Sword and shield")
	await wait_for_step("arm")
	await idle()
	var right: Dictionary = await scene.fight.equip("practice_sword", "right")
	var left: Dictionary = await scene.fight.equip("wicker_shield", "left")
	var kit: Dictionary = scene.run_state.player.get("equipped", {})
	print("  %s / %s -> %s" % [right.get("text", right.get("reason", "")), left.get("text", left.get("reason", "")), kit])
	if kit.get("right") != "practice_sword" or kit.get("left") != "wicker_shield":
		blocker("sword and shield aren't both in hand: " + str(kit))

	print("\n== The bout")
	if not await wait_for_step("bout"):
		blocker("arming didn't move on to the bout: " + step_id())
	await beside(KADE)
	var fought := false
	waited = 0.0
	while waited < 60.0:
		await create_timer(0.3).timeout
		waited += 0.3
		if scene.ui.guide.is_open():
			await read_cards()
		if scene.in_fight():
			fought = true
			var toward := cell_of(KADE) - Vector2(scene.run_state.player.x, scene.run_state.player.y)
			if toward.length() > 0.5:
				scene.facing_row = scene._facing_for(toward.normalized())
			await scene.fight.strike("right")
		elif fought or step_id() != "bout":
			break
	var outcome: Array = scene.run_state.journal.filter(func(e) -> bool: return str(e.get("category", "")).begins_with("spar_"))
	print("  bout: fought %s, outcome %s" % [fought, outcome.map(func(e) -> String: return str(e.reason))])
	if not fought:
		blocker("the bout never started")

	print("\n== Tell Kade why you're here")
	if not await wait_for_step("why"):
		blocker("the bout didn't move on: " + step_id())
	await bar_line("I'm trying to get into the city.", "say", KADE)
	var kade_job = scene.ui.npc_record(KADE).get("mind", {}).get("job")
	print("  Kade's job now: ", JSON.stringify(kade_job).left(120))

	print("\n== The steel file")
	if not await wait_for_step("steel"):
		blocker("answering Kade didn't move on: " + step_id())
	await walk_to(Vector2i(25, 29))
	var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
		{"verb": "take", "object_id": "steel_file", "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("take")})
	if reply.ok:
		scene._accept_state(reply.data.state)
	print("\n== The fire, where Kade can see it")
	if not await wait_for_step("fire"):
		blocker("picking up the file didn't move on: " + step_id())
	await beside(KADE)
	print("  %.1f cells from Kade" % cell_of(KADE).distance_to(Vector2(scene.run_state.player.x, scene.run_state.player.y)))
	await bar_line("strike the flint against the steel file so the sparks fall into the dry grass, then blow on it until it catches", "do")
	await shot("fire")
	if not await wait_for_step("captain", 20.0):
		blocker("the fire didn't count: " + step_id())

	print("\n== Kade's word, and the captain")
	waited = 0.0
	var vouched := -1.0
	while waited < 180.0 and not scene.run_state.get("admitted"):
		await create_timer(1.0).timeout
		waited += 1.0
		if scene.ui.guide.is_open():
			await read_cards()
		var roderic: Dictionary = scene.ui.npc_record(RODERIC)
		if vouched < 0.0 and roderic.get("mind", {}).get("memories", []).any(func(m) -> bool: return m.get("kind") == "vouch"):
			vouched = waited
			print("  Kade spoke to Roderic after %.0f s; wants_in: %s" % [waited, scene.run_state.tutorial.get("flags", {})])
	print("  admitted: %s after %.0f s (Roderic %.1f cells away)" % [JSON.stringify(scene.run_state.get("admitted")).left(160),
		waited, cell_of(RODERIC).distance_to(Vector2(scene.run_state.player.x, scene.run_state.player.y))])
	if vouched < 0.0:
		blocker("Kade never spoke to the captain")
	if not scene.run_state.get("admitted"):
		blocker("Roderic never let the stranger in")
	await shot("admitted")
	for entry in scene.run_state.journal.slice(-8):
		if entry.get("kind") == "npc":
			print("     ", str(entry.get("reason", "")).left(200))
	await wait_for_step("city", 10.0)
	await read_cards()
	for _i in 20:
		await create_timer(0.2).timeout
		if scene.ui.modal_kind == "tutorial_end":
			break
	await shot("end")
	print("\n==== TUTORIAL PLAYTEST: at %s" % step_id())
	print("BLOCKERS (%d):" % blockers.size())
	for item in blockers:
		print("  - ", item)
	print("NOTES (%d):" % notes.size())
	for item in notes:
		print("  - ", item)
	quit(0 if blockers.is_empty() else 2)
