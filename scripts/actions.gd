extends Node
## What the stranger does (the one text line, a round, pick up and put down) and how it plays back:
## walking there first, then the world, then the result in the bar.

var game: Node2D # The game (scripts/main.gd), whose child this is.


const NEARBY_CELLS := 8.0 # Try Something can involve anything this close; the player walks there first.


## Walk the player along the cells the server planned, with the normal walk animation.
func walk_along(path: Array) -> void:
	if path.is_empty():
		return
	game.scripted_walk = true
	for cell in path:
		var goal: Vector2 = game.cell_center(int(cell[0]), int(cell[1]))
		while game.player.position.distance_to(goal) > 0.5:
			var delta := get_process_delta_time()
			var before: Vector2 = game.player.position
			game.player.position = game.player.position.move_toward(goal, game.WALK_SPEED * delta)
			var step: Vector2 = game.player.position - before
			if step.length() > 0.01:
				game.facing_row = game.facing_for(step.normalized())
			game.player_visual.set_motion(game.facing_row, "walk", step.length(), delta)
			await get_tree().process_frame
	game.player_visual.set_motion(game.facing_row, "idle", 0.0, 0.0)
	game.predicted_cell = Vector2i(int(path[-1][0]), int(path[-1][1]))
	game.scripted_walk = false


## What a Try Something attempt can involve: carried items, anything intact within reach
## (whoever owns it, including trees), and people within reach.
func try_candidates() -> Array[Dictionary]:
	var carried: Array[Dictionary] = []
	var within_reach: Array[Dictionary] = []
	var here := Vector2(game.predicted_cell)
	for id in game.run_state.get("objects", {}):
		var obj: Dictionary = game.run_state.objects[id]
		if str(obj.condition) != "usable":
			continue
		if obj.holder_id == "player":
			carried.append(obj)
		elif obj.holder_id == null and here.distance_to(Vector2(int(obj.x), int(obj.y))) <= NEARBY_CELLS:
			within_reach.append(obj)
	for npc in game.run_state.get("npcs", []):
		if here.distance_to(Vector2(int(npc.x), int(npc.y))) <= NEARBY_CELLS:
			within_reach.append({"id": npc.id, "name": npc.name, "person": true, "alive": npc.get("alive", true)})
	carried.append_array(within_reach)
	return carried


func owner_name(obj: Dictionary) -> String:
	if obj.get("owner_id") == null:
		return ""
	if obj.owner_id == "player":
		return "you"
	for npc in game.run_state.get("npcs", []):
		if npc.id == obj.owner_id:
			return str(npc.name)
	return str(obj.owner_id)


## The one text line (GDD D-34): whatever the stranger typed goes to /act, which works out whether it is
## speech, a deed, both, waiting, giving up or walking away. Rounds play back in the dialogue bar;
## attempts outside a face-to-face walk, play out in the world, and land in the bar's log.
func act(text: String, target: String, selected_ids: Array, mode := "") -> void:
	if not await game.claim():
		return
	game.ui.bar.wait(text)
	var body := {"text": text, "selected_ids": selected_ids, "expected_version": game.run_state.event_seq,
		"request_id": game.request_id("act")}
	if not target.is_empty():
		body["target_id"] = target
	if mode in ["say", "do"]: # The bar's Say / Do switch (D-55): the backend takes it as given.
		body["mode"] = mode
	game.intent_pending = true
	var reply: Dictionary = await game.net.post(game.run_path("/act"), body, 16.0, false, _waiting_on(target))
	game.intent_pending = false
	if not reply.ok:
		await _act_failed(reply)
		return
	var heard = reply.data.get("intent")
	game.ui.bar.last_intent = heard if typeof(heard) == TYPE_DICTIONARY else {}
	if typeof(reply.data.get("round")) == TYPE_DICTIONARY:
		await _play_round_reply(reply.data, target)
	elif reply.data.has("notice"):
		game.request_busy = false
		game.accept_state(reply.data.state)
		game.ui.bar.note(str(reply.data.notice))
	else:
		await _play_attempt_reply(reply.data)


func _accept_result(state: Dictionary) -> void:
	while game.movement_sync_active:
		await get_tree().process_frame
	game.accept_state(state)
	game.move_queue.clear()
	game.snap_to_server()


## An attempt outside a face-to-face: walk there, let it happen in the world, then the result.
func _play_attempt_reply(data: Dictionary) -> void:
	await _accept_result(data.state)
	game.last_trace = data.get("trace")
	var entry: Dictionary = data.state.last_action

	game.view.start_fall(entry) # Copy the falling thing before the sync hides it.
	game.view.sync()
	game.view.reveal_new_objects(entry)
	game.view.play_harm(entry)
	_show_outcome(entry)
	var dramatic: bool = typeof(entry.get("transformed")) == TYPE_DICTIONARY or typeof(entry.get("harm")) == TYPE_DICTIONARY
	if dramatic and entry.category in ["success", "partial_success"]:
		await get_tree().create_timer(1.2).timeout # Let the fall or the blow play out in view.
	game.request_busy = false
	game.ui.bar.result(entry, game.last_trace)
	story_moved_on()


## How the stranger's own deed lands: a sound and a gesture when it works, the failure sound when it doesn't
## (D-55: heard as well as read). The same in the world and in a round's playback.
func _show_outcome(entry: Dictionary) -> void:
	if entry.category in ["success", "partial_success"]:
		game.effects.pickup_sound.play()
		game.player_visual.play_gesture("pickup" if entry.get("action") == "take" else "gesture")
	elif str(entry.category) in ["failed", "blocked", "unsupported", "unresolved"]:
		game.ui.sounds.play("fail")


## After an attempt or a round (their states arrive outside _accept_state): the device and the tutorial's cards
## catch up at once, not when the bar closes (D-53).
func story_moved_on() -> void:
	game.ui.device.refresh()
	game.ui.guide.refresh()
	game.ui.layers.refresh()
	game.ui.hud.refresh()


## A round: walk over first if the server planned it, then the bar plays it back line by line.
func _play_round_reply(data: Dictionary, target: String) -> void:
	game.last_trace = data.get("trace")
	var before_action = game.run_state.get("last_action")
	var round: Dictionary = data.round
	await _accept_result(data.state)

	var entry = data.state.get("last_action")
	var did: bool = typeof(entry) == TYPE_DICTIONARY and entry != before_action
	if did:
		game.view.start_fall(entry)
	game.request_busy = false
	game.view.sync()
	played_action = entry if did else {}
	# The bar plays the round back line by line; round_beat() gives each line its moment in the world.
	if game.in_encounter():
		game.ui.bar.open(target, "", round)
	else:
		game.ui.bar.ended(round)
	if not game.ui.bar.round_playing: # Nothing to play back: the story catches up now (else when playback ends).
		story_moved_on()


## Nothing happened: say why honestly, reconcile with the server, and hand the words back.
func _act_failed(reply: Dictionary) -> void:
	var detail = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
	var problem := str(detail.get("message")) if typeof(detail) == TYPE_DICTIONARY and detail.has("message") \
		else reply_problem(reply)
	await game.reconcile()
	game.request_busy = false
	game.ui.bar.problem(problem)


func reply_problem(reply: Dictionary) -> String:
	if int(reply.status) == 0:
		return "The local simulation didn't answer in time. Your journey is safe."
	if int(reply.status) >= 500:
		return "The world stumbled (HTTP %s). Your journey is safe; try again." % reply.status
	var detail = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
	if typeof(detail) == TYPE_DICTIONARY and str(detail.get("reason", "")) == "in_progress":
		return "You're still working on your last attempt."
	if typeof(detail) == TYPE_STRING:
		return detail
	return "The attempt couldn't be completed (HTTP %s). Your journey is safe." % reply.status


## What the busy indicator says while this waits (D-70): the person you're facing thinking, or the world working
## out a deed.
func _waiting_on(target: String, face_to_face := false) -> String:
	var person: Dictionary = game.ui.npc_record(target) if not target.is_empty() else {}
	if not person.is_empty():
		return "%s is thinking…" % str(person.get("name", "They"))
	if face_to_face or game.in_encounter():
		return "They're thinking…"
	return "Working out what happens…"


## A plain round move without words: walking away (Esc), or waiting / giving up from the tools.
## Face to face, everyone else's committed actions resolve at the same moment on the server.
func encounter_act(kind: String, text: String, target: String) -> void:
	if not await game.claim():
		return
	var greeting := "You come up to %s." % str(game.ui.npc_record(target).get("name", "them"))
	game.ui.bar.wait({"leave": "You walk away.", "wait": "You wait.", "yield": "You give up.", "greet": greeting}.get(kind, text))
	var body := {"kind": kind, "text": text, "selected_ids": [], "expected_version": game.run_state.event_seq,
		"request_id": game.request_id("round")}
	if not target.is_empty():
		body["target_id"] = target
	game.intent_pending = true
	var reply: Dictionary = await game.net.post(game.run_path("/encounter/act"), body, 16.0, false, _waiting_on(target, true))
	game.intent_pending = false
	if reply.ok:
		await _play_round_reply(reply.data, target)
	else:
		await _act_failed(reply)


var played_action: Dictionary = {} # The stranger's Try Something in the round being played back.


## One line of a round, as it happens in the world: a blow lands, someone gestures as they speak.
func round_beat(entry: Dictionary) -> void:
	var who := str(entry.get("who", ""))
	if who == "player":
		if entry.get("kind") == "do" and not played_action.is_empty():
			game.view.reveal_new_objects(played_action)
			game.view.play_harm(played_action)
			_show_outcome(played_action)
		return
	var actor := game.get_node_or_null("NPCs/%s/PaintedActor" % who)
	if actor and entry.get("kind") in ["strike", "reply", "arrive"]:
		actor.play_gesture("gesture")
	if entry.get("kind") == "strike" and not "misses" in str(entry.text):
		var npc_actor := game.get_node_or_null("NPCs/" + who) as Node2D
		game.player_visual.hurt(1.0 if npc_actor == null or npc_actor.position.x <= game.player.position.x else -1.0)
		game.shake_camera()


## After the round has played out: the death screen if the stranger fell.
func round_played() -> void:
	played_action = {}
	story_moved_on()
	var last = game.run_state.get("last_round")
	if typeof(last) == TYPE_DICTIONARY and last.get("arrested", false) and game.run_state["player"].get("alive", true):
		game.request_busy = true # Nothing else happens while the guards march you off.
		await get_tree().create_timer(1.8).timeout # Time to read what happened.
		game.ui.bar.close()
		game.ui.close_modal_now()
		await game.ui.fade(1.0)
		game.snap_to_server()
		game.camera.reset_smoothing()
		game.view.sync()
		await get_tree().create_timer(0.5).timeout
		await game.ui.fade(0.0)
		game.request_busy = false
		var arrests: Array = game.run_state.get("journal", []).filter(func(e) -> bool: return e.get("kind") == "arrest")
		game.ui.notify(str(arrests[-1].reason) if arrests else "The guards march you off.") # The map says where (D-59).
	if not game.run_state["player"].get("alive", true) and game.gameplay_active:
		await game.die()


## Pick up (or steal) and put down: decided by code on the server, which plans the walk there first.
func quick_action(verb: String, id: String) -> void:
	if not await game.claim():
		return
	var body := {"verb": verb, "object_id": id, "expected_version": game.run_state.event_seq,
		"request_id": game.request_id(verb)}
	var reply: Dictionary = await game.net.post(game.run_path("/quick"), body)
	if reply.ok:
		game.run_state = reply.data.state
		var entry: Dictionary = game.run_state.last_action
		await walk_along(entry.get("walk", []))
		game.request_busy = false
		game.view.sync()
		var claims: Array = entry.get("property", [])
		if entry.category == "success" and not claims.is_empty():
			var owner := str(game.ui.npc_record(str(claims[0].owner_id)).get("name", "someone"))
			game.ui.notify("You take the %s. It belongs to %s." % [claims[0].name, owner])
		else:
			game.ui.notify(str(entry.reason))
		if entry.category == "success":
			game.effects.pickup_sound.play()
			game.player_visual.play_gesture("pickup" if verb == "take" else "gesture")
			if verb == "take":
				game.ui.hud.show_hint("pack", "It's in your pack (bottom of the screen). Drag it onto someone or "
					+ "something to use it; right-click it to look closer.")
		if game.ui.modal_kind == "inventory":
			game.ui.pack.open()
		return
	# Reconcile a lost response before allowing another world-changing action.
	var detail = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
	var fresh: Dictionary = await game.net.api(HTTPClient.METHOD_GET, game.run_path())
	if fresh.ok:
		game.run_state = fresh.data
		game.view.sync()
	else:
		game.sync_error = true
	game.request_busy = false
	game.ui.notify("Not now: deal with who's in front of you first." if typeof(detail) == TYPE_DICTIONARY
		and str(detail.get("reason", "")) == "encounter_active" else "Could not confirm the action. Your saved journey is preserved.")
