extends Node
## Immediate presentation, one ordered command lane, and backend-owned combat/equipment rules.

const Projectile := preload("res://scripts/projectile.gd")
const HeldArt := preload("res://scripts/held_art.gd")
const Actor := preload("res://scripts/painted_actor.gd")

var game: Node2D
var table: Dictionary = {}
var busy := false
var guarding := false
var guard_facing := Vector2.ZERO
var commands: Array[Dictionary] = []
var buffers := {}
var local_ready := {}
var journey := ""
var equipment_key := ""
var health_seen := {}
var seen_swings := {}
var seen_shots := {}
var view_images := {}
var view_state := {}


func _ready() -> void:
	var file := FileAccess.open("res://data/content/gear.json", FileAccess.READ)
	if file:
		table = JSON.parse_string(file.get_as_text())


func _exit_tree() -> void:
	HeldArt.standins.clear()
	HeldArt.layouts.clear()
	Actor._sheets.clear()


func _process(_delta: float) -> void:
	if game == null or game.run_state.is_empty():
		return
	if not game.gameplay_active or game.ui.blocks_movement() or limited("hands") or game.run_state.player.get("down", false):
		clear_buffers()
		if guarding:
			guard(false)
		return
	for hand in buffers.keys():
		var queued: Dictionary = buffers[hand]
		if Time.get_ticks_msec() > int(queued.expires):
			buffers.erase(hand)
		elif readiness(hand) <= 0:
			buffers.erase(hand)
			strike(str(hand), bool(queued.throw))
	if guarding and not facing_vector().is_equal_approx(guard_facing):
		guard(true, true)


func clear_buffers() -> void:
	buffers.clear()


func limited(limit: String) -> bool:
	for effect in game.run_state.get("player", {}).get("states", []):
		if limit in effect.get("limits", []):
			return true
	return false


func needs_active_clock() -> bool:
	var action: bool = busy or not buffers.is_empty() or game.in_fight()
	action = action or not game.run_state.get("player", {}).get("swings", {}).is_empty()
	return action or not game.run_state.get("projectiles", []).is_empty()


func clock_interval_ms() -> float:
	return float(table.get("combat", {}).get("clock_ms", 100) if needs_active_clock() \
		else table.get("combat", {}).get("idle_clock_ms", 500))


func gear_view(obj: Dictionary) -> Dictionary:
	return game.run_state.get("view", {}).get("gear", {}).get(str(obj.get("id", "")), {})


func weapon_spec(obj: Dictionary) -> Dictionary:
	var derived: Dictionary = gear_view(obj).get("profile", {})
	if not derived.is_empty():
		return derived
	# Legacy servers remain displayable; new servers always provide carried profiles.
	if obj.is_empty():
		return table.get("weapons", {}).get("fists", {})
	return table.get("weapons", {}).get(str(obj.get("gear", {}).get("class", "improvised")), table.get("weapons", {}).get("improvised", {}))


func in_hand(person: Dictionary, hand: String) -> Dictionary:
	var kit: Dictionary = person.get("equipped", {}) if typeof(person.get("equipped")) == TYPE_DICTIONARY else {}
	var obj: Dictionary = game.run_state.get("objects", {}).get(str(kit.get(hand, "")), {})
	if str(obj.get("holder_id", "")) != str(person.get("id", "player")) \
			or str(obj.get("condition", "")) in ["broken", "gone", "destroyed"] or obj.get("shut_in"):
		return {}
	return obj


func shield_hand() -> String:
	for hand in ["left", "right"]:
		var obj := in_hand(game.run_state.get("player", {}), hand)
		if str(gear_view(obj).get("record", obj.get("gear", {})).get("kind", "")) == "shield" and weapon_spec(obj).get("usable", true):
			return hand
	return ""


func readiness(hand: String) -> int:
	var elapsed := maxi(0, int((Time.get_ticks_usec() - game.last_state_usec) / 1000)) if game.last_state_usec > 0 else 0
	var now := int(game.run_state.get("sim_time_ms", 0)) + mini(elapsed, 200)
	var swing: Dictionary = game.run_state.player.get("swings", {}).get(hand, {})
	var until := maxi(int(game.run_state.player.get("ready_at", {}).get(hand, 0)), int(swing.get("recover_until", 0)))
	return maxi(until - now,
		int(local_ready.get(hand, 0)) - Time.get_ticks_msec())


func strike(hand: String, throw := false) -> void:
	if not game.gameplay_active or game.sync_error or limited("hands") or game.run_state.player.get("down", false):
		return
	var held := in_hand(game.run_state.player, hand)
	if held.get("readable") != null and not throw:
		game.ui.open_book(held)
		return
	var remaining := readiness(hand)
	var buffer_ms := int(table.get("combat", {}).get("buffer_ms", 180))
	if remaining > 0:
		if remaining <= buffer_ms:
			buffers[hand] = {"throw": throw, "expires": Time.get_ticks_msec() + buffer_ms}
		return
	if commands.any(func(c: Dictionary) -> bool: return c.path == "/strike" and c.body.hand == hand):
		return
	var spec := weapon_spec(held)
	var windup := float(table.get("thrown", {}).get("windup_ms", 320)) if throw else float(spec.get("windup_ms", 260))
	var recovery := float(table.get("thrown", {}).get("recover_ms", 350)) if throw else float(spec.get("recover_ms", 200))
	local_ready[hand] = Time.get_ticks_msec() + int(windup + recovery)
	# On this input frame: no network await precedes anticipation. Hits are never predicted.
	game.player_visual.play_attack("throw" if throw else str(spec.get("animation", "punch")), windup, hand,
		recovery, 0.0, "predicted:" + game.request_id("pose"), facing_vector())
	var reply: Dictionary = await _command("/strike", {"hand": hand, "throw": throw})
	if not _result(reply, "strike").get("ok", false):
		local_ready.erase(hand)
		game.player_visual.cancel_attack(hand)
		_notify(reply, "strike")


func guard(raised: bool, turn := false) -> void:
	if (raised == guarding and not turn) or not game.gameplay_active:
		return
	var hand := shield_hand()
	if raised and hand.is_empty():
		return
	guarding = raised
	guard_facing = facing_vector()
	game.player_visual.set_guard(raised, hand if not hand.is_empty() else "left")
	# Replace queued turns rather than piling requests up while the player rotates.
	for command in commands:
		if command.path == "/guard":
			command.body.raised = raised
			return
	var reply: Dictionary = await _command("/guard", {"raised": raised})
	if not _result(reply, "guard").get("ok", false):
		guarding = false
		game.player_visual.set_guard(false)


func swap() -> void:
	clear_buffers()
	var reply: Dictionary = await _command("/swap", {})
	_notify(reply, "swap")


func equip(object_id: String, slot: String) -> Dictionary:
	clear_buffers()
	var body := {"object_id": object_id}
	if not slot.is_empty():
		body.slot = slot
	var reply: Dictionary = await _command("/equip", body)
	return _result(reply, "equip")


func treat(object_id: String, condition: int, patient := "player") -> Dictionary:
	var reply: Dictionary = await _command("/treat", {"object_id": object_id, "condition": condition, "patient_id": patient})
	return _result(reply, "treat")


func _result(reply: Dictionary, action: String) -> Dictionary:
	if reply.get("ok", false) and typeof(reply.get("data")) == TYPE_DICTIONARY:
		return reply.data.get(action, {})
	return {"ok": false, "reason": "Could not do that just now."}


func _command(path: String, body: Dictionary) -> Dictionary:
	if not game.gameplay_active:
		return {"ok": false}
	var command := {"path": path, "body": body, "run": str(game.run_state.run_id)}
	commands.append(command)
	if not busy:
		_drain()
	while not command.has("reply"):
		await get_tree().process_frame
	return command.reply


func _drain() -> void:
	busy = true
	while not commands.is_empty():
		while game.movement_sync_active:
			await get_tree().process_frame
		var command: Dictionary = commands.pop_front()
		if not game.gameplay_active or str(game.run_state.get("run_id", "")) != str(command.run):
			command.reply = {"ok": false}
			continue
		# Save at most one bounded batch of preceding positions, then give the command priority.
		if not game.move_queue.is_empty():
			await game._flush_moves(true)
		game.movement_sync_active = true
		var body: Dictionary = command.body.duplicate()
		body.expected_version = game.run_state.event_seq
		body.request_id = game.request_id(str(command.path).trim_prefix("/"))
		if command.path in ["/strike", "/guard"]:
			var ahead := facing_vector()
			body.facing = [ahead.x, ahead.y]
		if command.path == "/strike":
			var spec := weapon_spec(in_hand(game.run_state.player, str(body.hand)))
			var reach := float(spec.get("range") if spec.get("range") != null else spec.get("reach", 1.5))
			var target := _aim(8.0 if body.throw else reach)
			if not target.is_empty():
				body.target_id = target
		var reply: Dictionary = await game.net.post("/runs/%s%s" % [command.run, command.path], body)
		var detail: Dictionary = reply.get("data", {}).get("detail", {}) \
			if typeof(reply.get("data")) == TYPE_DICTIONARY and typeof(reply.data.get("detail")) == TYPE_DICTIONARY else {}
		if not reply.get("ok", false) and int(reply.get("status", 0)) == 409 and detail.get("reason") == "stale_state":
			var fresh: Dictionary = await game.net.api(HTTPClient.METHOD_GET, "/runs/" + str(command.run))
			if fresh.get("ok", false) and str(game.run_state.get("run_id", "")) == str(command.run):
				game.accept_state(fresh.data)
				body.expected_version = game.run_state.event_seq
				body.request_id = game.request_id("combat-retry")
				reply = await game.net.post("/runs/%s%s" % [command.run, command.path], body)
		if reply.get("ok", false) and str(game.run_state.get("run_id", "")) == str(command.run):
			game.accept_state(reply.data.state)
		game.movement_sync_active = false
		command.reply = reply
	busy = false


func _notify(reply: Dictionary, action: String) -> void:
	var data: Dictionary = reply.get("data", {}) if typeof(reply.get("data")) == TYPE_DICTIONARY else {}
	var result: Dictionary = data.get(action, {})
	if result.get("ok") == false:
		game.ui.notify(str(result.get("reason", "")))


func facing_vector() -> Vector2:
	return ([Vector2.DOWN, Vector2.LEFT, Vector2.UP, Vector2.RIGHT, Vector2(1, 1), Vector2(-1, 1),
		Vector2(-1, -1), Vector2(1, -1)][game.facing_row] as Vector2).normalized()


func _aim(range_cells: float) -> String:
	var ahead := facing_vector()
	var hovered: Dictionary = game.ui.cursor.pick(game.get_global_mouse_position())
	if range_cells > 3.0 and not hovered.is_empty() and str(hovered.get("kind", "")) == "npc":
		return str(hovered.id)
	var target := ""
	var best: float = maxf(2.2, range_cells + 0.6) * float(game.CELL)
	for npc in game.run_state.get("npcs", []):
		if not npc.get("alive", true) or npc.get("down", false):
			continue
		var actor := game.get_node_or_null("NPCs/" + str(npc.id)) as Node2D
		if actor == null:
			continue
		var toward: Vector2 = actor.position - game.player.position
		if toward.length() < best and (toward.length() < 8.0 or toward.normalized().dot(ahead) > 0.3):
			best = toward.length()
			target = str(npc.id)
	return target


func sync() -> void:
	var state: Dictionary = game.run_state
	if state.is_empty():
		return
	if journey != str(state.run_id):
		journey = str(state.run_id)
		clear_buffers()
		local_ready.clear()
		seen_swings.clear()
		seen_shots.clear()
		health_seen.clear()
		equipment_key = ""
		guarding = false
	var next_key := JSON.stringify(state.player.get("equipped", {}))
	if next_key != equipment_key:
		equipment_key = next_key
		clear_buffers()
		local_ready.clear()
		for hand in game.player_visual.attacks.keys():
			game.player_visual.cancel_attack(str(hand))
	_sync_gear(state.player, game.player_visual)
	for npc in state.get("npcs", []):
		var painted: Node = game.get_node_or_null("NPCs/%s/PaintedActor" % npc.id)
		if painted:
			_sync_gear(npc, painted)
			if health_seen.has(npc.id) and float(npc.get("health", 100)) < float(health_seen[npc.id]):
				painted.hurt()
			health_seen[npc.id] = npc.get("health", 100)
	var fight: Dictionary = state.get("fight", {}) if typeof(state.get("fight")) == TYPE_DICTIONARY else {}
	for who in fight.get("swings", {}):
		var painted: Node = game.get_node_or_null("NPCs/%s/PaintedActor" % who)
		if painted:
			_show_swing(str(who), painted, fight.swings[who], state)
	for hand in state.player.get("swings", {}):
		_show_swing("player:" + str(hand), game.player_visual, state.player.swings[hand], state)
	_align_clocks(state)
	var active_shots := {}
	for shot in state.get("projectiles", []):
		active_shots[shot.id] = true
		if seen_shots.has(shot.id):
			continue
		seen_shots[shot.id] = true
		var flying := Projectile.new()
		flying.from = game.cell_center(int(shot.from[0]), int(shot.from[1])) + Vector2(0, -40)
		flying.to = game.cell_center(int(shot.to[0]), int(shot.to[1])) + Vector2(0, -36)
		flying.flight_s = maxf(0.1, (float(shot.lands_at) - float(state.sim_time_ms)) / 1000.0)
		var profile: Dictionary = shot.get("profile", {})
		flying.kind = "arrow" if str(profile.get("ammo", "")) == "arrow" else "stone" if profile.get("ammo") else "thrown"
		if shot.get("object_id") != null:
			flying.texture = game.art.texture_for(state.objects.get(str(shot.object_id), {"id": str(shot.object_id)}))
		game.add_child(flying)
	seen_shots = active_shots


func _align_clocks(state: Dictionary) -> void:
	for hand in game.player_visual.attacks:
		var blow: Dictionary = game.player_visual.attacks[hand]
		var key := str(blow.get("key", ""))
		if not key.is_valid_int() or blow.has("cancel_at"):
			continue
		var elapsed := maxi(0, int(state.sim_time_ms) - int(key))
		# Readiness is written on contact. Before it, the accepted swing owns the full timeline.
		var swing: Dictionary = state.player.get("swings", {}).get(hand, {})
		var ready := maxi(int(state.player.get("ready_at", {}).get(hand, 0)), int(swing.get("recover_until", 0)))
		blow.recovery = maxf(.05, (float(ready - int(key)) / 1000.0) - float(blow.windup))
		if blow.has("server_elapsed"):
			blow.server_elapsed = lerpf(float(blow.server_elapsed), float(elapsed) / 1000.0, .4)
		local_ready[hand] = Time.get_ticks_msec() + maxi(0, ready - int(state.sim_time_ms))
	var fight: Dictionary = state.get("fight", {}) if typeof(state.get("fight")) == TYPE_DICTIONARY else {}
	for who in fight.get("recover", {}):
		var painted: Node = game.get_node_or_null("NPCs/%s/PaintedActor" % who)
		if painted == null:
			continue
		for blow in painted.attacks.values():
			var key := str(blow.get("key", ""))
			if key.is_valid_int() and not blow.has("cancel_at"):
				var until := int(fight.recover[who])
				# A prior recovery can coexist with the next wind-up; never shrink that new swing.
				if until > int(key) + int(float(blow.windup) * 1000.0):
					blow.recovery = maxf(.05, float(until - int(key)) / 1000.0 - float(blow.windup))


func _show_swing(who: String, painted: Node, swing: Dictionary, state: Dictionary) -> void:
	var key := int(swing.get("started", 0))
	if seen_swings.get(who, -1) == key:
		return
	seen_swings[who] = key
	var elapsed := maxi(0, int(state.sim_time_ms) - key)
	painted.reconcile_attack(swing, float(elapsed))
	if who.begins_with("player:"):
		var hand := who.trim_prefix("player:")
		var ready := int(state.player.get("ready_at", {}).get(hand, swing.get("recover_until", 0)))
		local_ready[hand] = Time.get_ticks_msec() + maxi(0, ready - int(state.sim_time_ms))


func _sync_gear(person: Dictionary, painted: Node) -> void:
	var holding := {}
	var right := in_hand(person, "right")
	for hand in ["right", "left"]:
		var obj := in_hand(person, hand)
		if obj.is_empty() or (hand == "left" and str(right.get("id", "")) == str(obj.id)):
			continue
		if str(person.get("id", "player")) != "player" and gear_view(obj).is_empty():
			continue # Concealed equipment never reaches the public render view.
		var spec := weapon_spec(obj)
		var kind := str(gear_view(obj).get("record", obj.get("gear", {})).get("kind", ""))
		var texture: Texture2D = _view_texture(str(obj.held_asset_id), true) if obj.get("held_asset_id") else null
		if texture == null:
			texture = HeldArt.fallback(spec, obj)
		var animation := str(spec.get("animation", "slash"))
		var layout := HeldArt.layout(texture, animation, kind)
		if not layout.get("suitable", true):
			texture = HeldArt.fallback(spec, obj)
			layout = HeldArt.layout(texture, animation, kind)
		holding[hand] = {"texture": texture, "animation": animation, "kind": kind, "hands": int(spec.get("hands", 1)),
			"object_id": str(obj.id), "layout": layout,
			"length_m": float(obj.length_m) if obj.get("length_m") != null else maxf(0.25, sqrt(float(obj.get("mass_kg", 0.5))) * 0.5)}
	var wearing := {}
	for slot in ["head", "body", "legs", "feet"]:
		var obj := in_hand(person, slot)
		if obj.is_empty() or obj.get("no_overlay", false) or not obj.get("worn_asset_id"):
			continue
		var sheet = _view_image(str(obj.worn_asset_id))
		if sheet != null:
			wearing[slot] = sheet
	painted.set_gear(holding, wearing)
	var raised: bool = typeof(person.get("guard")) == TYPE_DICTIONARY and person.guard.get("raised", false)
	var hand := str(person.get("guard", {}).get("hand", "left")) if typeof(person.get("guard")) == TYPE_DICTIONARY else "left"
	if painted == game.player_visual:
		painted.set_guard(guarding, shield_hand() if not shield_hand().is_empty() else hand)
	else:
		painted.set_guard(raised, hand)


func _view_texture(asset_id: String, trim: bool) -> Texture2D:
	var image = _view_image(asset_id)
	if image == null:
		return null
	if not view_images.has(asset_id + ":texture"):
		var copy: Image = image.duplicate()
		if trim:
			var used: Rect2i = Actor.solid_rect(copy)
			if used.size.x > 0:
				copy = copy.get_region(used)
		view_images[asset_id + ":texture"] = ImageTexture.create_from_image(copy)
	return view_images[asset_id + ":texture"]


func _view_image(asset_id: String):
	if view_images.has(asset_id):
		return view_images[asset_id]
	var cached := "user://assets/%s.png" % asset_id
	if FileAccess.file_exists(cached):
		var image := Image.load_from_file(cached)
		if image:
			view_images[asset_id] = image
			return image
	if not view_state.has(asset_id):
		_poll_view(asset_id)
	return null


func _poll_view(asset_id: String) -> void:
	view_state[asset_id] = "polling"
	for _attempt in 60:
		var reply: Dictionary = await game.net.fetch_asset(asset_id)
		if game.run_state.is_empty():
			break
		if reply.status == 200:
			var image := Image.new()
			if image.load_png_from_buffer(reply.body) == OK:
				DirAccess.make_dir_recursive_absolute("user://assets")
				image.save_png("user://assets/%s.png" % asset_id)
				view_images[asset_id] = image
				view_state.erase(asset_id)
				sync()
				return
		if reply.status != 202:
			view_state[asset_id] = "failed"
			return
		await get_tree().create_timer(3.0).timeout
	view_state.erase(asset_id)
