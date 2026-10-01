extends SceneTree
## A scripted playtest of any training level (GDD D-59), with the live models: each step's cards are read, then its
## playtest is done through the game's own service (walk, take, say, do, the interface, asking the device), and the
## clock runs until the step is done. Needs the backend running live (./tools/run_m0.ps1):
##   Godot --path . --script res://tools/playtest_level.gd -- --level=cup_of_water [--route=2] [--capture]
## An advanced level's steps may have other routes to the same outcome (routes: {"2": [...]}); --route picks one
## (a step without it plays its playtest).
## Reports each step's time, the whole level's against its minutes, and ends with BLOCKERS and NOTES, like
## playtest_demo. Run against a stub backend it checks the script itself (attempts then fail as notes).
var scene: Node2D
var level := {}
var capture := false
var blockers: PackedStringArray = []
var notes: PackedStringArray = []
var blocked := {}
var size := Vector2i.ZERO
var route := "1"
var obstacle_cells := {}


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
	root.get_texture().get_image().save_png("res://docs/screenshots/play_%s_%s.png" % [level.id, name])


func step_index() -> int:
	var progress = scene.run_state.get("tutorial")
	if typeof(progress) != TYPE_DICTIONARY:
		return -1
	return level.steps.size() if progress.get("done", false) else int(progress.step)


func read_cards() -> void:
	for _i in 40:
		await create_timer(0.15).timeout
		if scene.ui.guide.is_open():
			scene.ui.guide._next()
		elif not scene.ui.guide.sending:
			await create_timer(0.3).timeout
			if not scene.ui.guide.is_open():
				return


func post(path: String, body: Dictionary, timeout := 60.0) -> Dictionary:
	body.merge({"expected_version": scene.run_state.event_seq, "request_id": scene.request_id(path.get_file())})
	var reply: Dictionary = await scene.net.post(scene.run_path("/" + path), body, timeout)
	if reply.ok and typeof(reply.data) == TYPE_DICTIONARY and reply.data.has("state"):
		scene.accept_state(reply.data.state)
	elif typeof(reply.get("data")) == TYPE_DICTIONARY and reply.data.has("state"):
		scene.accept_state(reply.data.state)
	return reply


## The map's solid cells, as the server has them (data/maps).
func load_map() -> void:
	var plan: Dictionary = scene.map_plan
	size = Vector2i(int(plan.size[0]), int(plan.size[1]))
	for item in plan.get("buildings", []) + plan.get("obstacles", []):
		var c: Array = item.cells
		var cells: Array[Vector2i] = []
		for x in range(int(c[0]), int(c[0]) + int(c[2])):
			for y in range(int(c[1]), int(c[1]) + int(c[3])):
				blocked[Vector2i(x, y)] = true
				cells.append(Vector2i(x, y))
		obstacle_cells[str(item.name)] = cells


## Obstacles play has cleared (a felled tree, brambles cut out of a gap) no longer block the walk.
func unblock_cleared() -> void:
	for thing in scene.run_state.get("objects", {}).values():
		var name := str(thing.get("geometry_name", ""))
		if not name.is_empty() and str(thing.get("condition", "usable")) != "usable":
			for cell in obstacle_cells.get(name, []):
				blocked.erase(cell)


func path_to(start: Vector2i, goal: Vector2i) -> Array:
	var previous := {start: start}
	var frontier: Array[Vector2i] = [start]
	var reached := Vector2i(-1, -1)
	while not frontier.is_empty():
		var cell: Vector2i = frontier.pop_front()
		if Vector2(cell).distance_to(Vector2(goal)) <= 1.5:
			reached = cell
			break
		for step in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			var next: Vector2i = cell + step
			if previous.has(next) or blocked.has(next) or next.x < 0 or next.y < 0 or next.x >= size.x or next.y >= size.y:
				continue
			previous[next] = cell
			frontier.append(next)
	var cells := []
	while reached != Vector2i(-1, -1) and reached != start:
		cells.push_front([reached.x, reached.y])
		reached = previous[reached]
	return cells


func target_cell(target) -> Vector2i:
	if typeof(target) == TYPE_ARRAY:
		return Vector2i(int(target[0]), int(target[1]))
	for npc in scene.run_state.npcs:
		if npc.id == target:
			return Vector2i(int(npc.x), int(npc.y))
	var thing: Dictionary = scene.run_state.objects.get(str(target), {})
	return Vector2i(int(thing.get("x", 0)), int(thing.get("y", 0)))


func walk_to(target) -> void:
	unblock_cleared()
	var here := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	var cells := path_to(here, target_cell(target))
	for i in range(0, cells.size(), 20):
		var reply := await post("move", {"cells": cells.slice(i, i + 20)})
		if not reply.ok:
			note("couldn't walk to %s: %s" % [str(target), str(reply.get("data", ""))])
			return
	if not cells.is_empty():
		var last: Array = cells[-1]
		scene.predicted_cell = Vector2i(last[0], last[1])
		scene.player.position = scene.cell_center(last[0], last[1])


func toward(target) -> Array:
	var here := Vector2(float(scene.run_state.player.x), float(scene.run_state.player.y))
	var there := Vector2(target_cell(target))
	var way := (there - here).normalized() if there != here else Vector2(0, 1)
	return [way.x, way.y]


## World time passing, a second at a time, people thinking when they need to (up to seconds, or the step's end).
func beats(seconds: int, index: int) -> void:
	for _beat in seconds:
		if step_index() > index:
			return
		await post("explore", {"elapsed_ms": 1000})
		if scene.run_state.get("pending_minds", []):
			await post("think", {}, 60.0)


func act(action: Dictionary, index: int) -> void:
	if action.has("equip"):
		var thing_id := str(action.equip)
		var slot := str(action.get("slot", "right"))
		if thing_id.begins_with("made:"): # The newest thing the stranger made of this kind of gear (A5).
			var kind := thing_id.trim_prefix("made:")
			thing_id = ""
			for thing in scene.run_state.objects.values():
				var made_kind := str(thing.get("gear", {}).get("kind", ""))
				if thing.get("created_by") == "player" and thing.holder_id == "player" and made_kind == kind:
					thing_id = str(thing.id)
			if not action.has("slot"):
				slot = {"weapon": "right", "shield": "left"}.get(kind, "body")
			if thing_id.is_empty():
				note("nothing made of kind %s to take up" % kind)
				return
		await post("equip", {"object_id": thing_id, "slot": slot})
	elif action.has("strike"):
		for _swing in int(action.get("repeat", 1)):
			if step_index() > index:
				return
			var facing := toward(action.at) if action.has("at") else [0.0, -1.0]
			await post("strike", {"hand": str(action.strike), "facing": facing,
				"target_id": action.get("at")})
			await beats(1, index)
	elif action.has("guard"):
		await post("guard", {"raised": bool(action.guard),
			"facing": toward(action.toward) if action.has("toward") else [0.0, -1.0]})
	elif action.has("treat"):
		var patient := str(action.treat)
		var person: Dictionary = scene.run_state.player
		if patient != "player":
			person = scene.run_state.npcs.filter(func(n) -> bool: return n.id == patient)[0]
		var wound := -1
		for i in person.get("conditions", []).size():
			var c: Dictionary = person.conditions[i]
			if str(c.kind) == str(action.get("kind", "")) and int(c.get("treated", 0)) == 0:
				wound = i
		var remedy := ""
		for thing in scene.run_state.objects.values():
			if thing.holder_id == "player" and str(thing.get("gear", {}).get("kind", "")) == "remedy":
				remedy = str(thing.id)
		if wound < 0 or remedy.is_empty():
			note("nothing to treat %s's %s with" % [patient, str(action.get("kind", ""))])
			return
		var reply := await post("treat", {"object_id": remedy, "patient_id": patient, "condition": wound})
		print("     treat %s → %s" % [patient, str(reply.get("data", {}).get("treat", {}))])
	elif action.has("give_up"):
		await post("act", {"text": "I give up", "mode": "say", "selected_ids": []}, 90.0)
		scene.ui.bar.close()
	elif action.has("wait"):
		await beats(int(action.wait), index)
	elif action.has("walk_to"):
		await walk_to(action.walk_to)
	elif action.has("take"):
		var reply := await post("quick", {"verb": "take", "object_id": str(action.take)})
		if not reply.ok:
			note("couldn't take %s" % str(action.take))
	elif action.has("say"):
		var reply := await post("say", {"npc_id": str(action.to), "text": str(action.say)}, 90.0)
		if not reply.ok:
			note("couldn't talk to %s" % str(action.to))
		for line in scene.run_state.get("journal", []).slice(-6):
			if line.get("kind") == "talk" and str(line.get("npc_id", "")) == str(action.to):
				print("     %s: %s" % [str(action.to), str(line.get("reply", "")).left(160)])
		scene.ui.bar.close()
	elif action.has("do"):
		var body := {"text": str(action.do), "mode": "do", "selected_ids": []}
		if action.has("to"):
			body["target_id"] = str(action.to)
		var reply := await post("act", body, 120.0)
		var entry: Dictionary = {}
		for line in scene.run_state.get("journal", []):
			if line.get("kind") == "craft":
				entry = line
		print("     do “%s” → %s: %s" % [str(action.do), str(entry.get("category", "?")), str(entry.get("reason", "")).left(160)])
		scene.ui.bar.close()
	elif action.has("ui"):
		await post("tutorial/ui", {"key": str(action.ui)})
	elif action.has("ask"):
		var reply := await post("device/ask", {"question": str(action.ask)}, 60.0)
		if reply.ok:
			print("     device: %s" % str(scene.run_state.device_log[-1].text).left(160))


func _run() -> void:
	var id := "cup_of_water"
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--level="):
			id = arg.trim_prefix("--level=")
		elif arg.begins_with("--route="):
			route = arg.trim_prefix("--route=")
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	await scene.start("developer", id)
	await create_timer(1.0).timeout
	level = scene.level
	load_map()
	print("\n==== LEVEL PLAYTEST: %s (%s, about %d min, route %s)" % [level.title, id, int(level.minutes), route])
	var started := Time.get_ticks_msec()
	for index in level.steps.size():
		var step: Dictionary = level.steps[index]
		var began := Time.get_ticks_msec()
		await read_cards()
		if step_index() > index: # Done already: its cards were all it asked (or the world did it).
			print("-- %d %s (done on reading)" % [index + 1, step.id])
			continue
		if step_index() < index:
			blocker("expected step %s, still at %d" % [step.id, step_index()])
			break
		print("-- %d %s" % [index + 1, step.id])
		for action in step.get("routes", {}).get(route, step.get("playtest", [])):
			await act(action, index)
		for _beat in 40: # Up to 40 s of world time for the step to see it happened.
			if step_index() > index:
				break
			await post("explore", {"elapsed_ms": 1000})
			if scene.run_state.get("pending_minds", []):
				await post("think", {}, 60.0)
		await shot(step.id)
		var seconds := (Time.get_ticks_msec() - began) / 1000.0
		if step_index() <= index:
			blocker("step %s didn't complete (%.0f s)" % [step.id, seconds])
			break
		print("   done in %.1f s" % seconds)
	await read_cards()
	var total := (Time.get_ticks_msec() - started) / 1000.0
	print("\n==== %s: %s in %.0f s (target %d min, without reading time)" % [id,
		"DONE" if step_index() >= level.steps.size() else "STOPPED", total, int(level.minutes)])
	print("BLOCKERS (%d):" % blockers.size())
	for item in blockers:
		print("  - ", item)
	print("NOTES (%d):" % notes.size())
	for item in notes:
		print("  - ", item)
	quit(0 if blockers.is_empty() else 2)
