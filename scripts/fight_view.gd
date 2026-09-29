extends Node
## The stranger's hands and body on screen (GDD D-49): Space and F strike with the right and left hands (holding
## F raises a shield), X swaps hands, Q throws what's in the right hand. It draws what everyone holds and wears,
## plays each blow's wind-up so it can be read and dodged, and flies arrows and thrown things. The backend decides
## everything; this only asks and shows.

const Projectile := preload("res://scripts/projectile.gd")

var game: Node2D
var table: Dictionary = {} # data/content/gear.json: weapon classes, remedies, armour.
var busy := false
var guarding := false
var seen_swings := {} # who -> the swing start already played
var seen_shots := {}
var view_images := {} # asset id -> Image (held views and worn sheets)
var view_state := {} # asset id -> "polling" | "failed"


func _ready() -> void:
	var file := FileAccess.open("res://data/content/gear.json", FileAccess.READ)
	if file:
		table = JSON.parse_string(file.get_as_text())


## The class spec of what's in a hand (fists when empty).
func weapon_spec(obj: Dictionary) -> Dictionary:
	var weapons: Dictionary = table.get("weapons", {})
	if obj.is_empty():
		return weapons.get("fists", {})
	var record = obj.get("gear")
	if typeof(record) == TYPE_DICTIONARY and str(record.get("kind", "")) == "shield":
		return {"animation": "bash", "windup_ms": 450, "hands": 1, "reach": 1.3}
	if typeof(record) == TYPE_DICTIONARY and weapons.has(str(record.get("class", ""))):
		return weapons[str(record["class"])]
	if float(obj.get("water_l", 0)) > 0.0:
		return weapons.get("container", {})
	return weapons.get("improvised", {})


func in_hand(person: Dictionary, hand: String) -> Dictionary:
	var kit = person.get("equipped")
	if typeof(kit) != TYPE_DICTIONARY or not kit.has(hand):
		return {}
	var obj: Dictionary = game.run_state.get("objects", {}).get(str(kit[hand]), {})
	var owner := str(person.get("id", "player"))
	return obj if str(obj.get("holder_id", "")) == owner and str(obj.get("condition", "")) != "broken" else {}


func shield_hand() -> String:
	for hand in ["left", "right"]:
		var obj := in_hand(game.run_state.get("player", {}), hand)
		if not obj.is_empty() and typeof(obj.get("gear")) == TYPE_DICTIONARY and str(obj.gear.get("kind", "")) == "shield":
			return hand
	return ""


# --- Asking the backend -----------------------------------------------------------------------------------------

## Space / F: a blow, a shot or a pour with that hand at whoever you face. The wind-up plays at once.
func strike(hand: String, throw := false) -> void:
	if busy or not game.gameplay_active or game.sync_error or game.run_state.get("player", {}).get("down", false):
		return
	busy = true
	var obj := in_hand(game.run_state.player, hand)
	var spec := weapon_spec(obj)
	var target := _aim(float(spec.get("range", spec.get("reach", 1.5))) if not throw else 8.0)
	var body := {"hand": hand, "throw": throw, "expected_version": game.run_state.event_seq,
		"request_id": game._request_id("strike")}
	if not target.is_empty():
		body["target_id"] = target
	while game.movement_sync_active: # Our steps first: the blow starts where we stand now.
		await get_tree().process_frame
	game.movement_sync_active = true
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/strike" % game.run_state.run_id, body)
	game.movement_sync_active = false
	busy = false
	if not reply.ok:
		var detail = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
		if typeof(detail) == TYPE_DICTIONARY:
			game.ui.notify(str(detail.get("message", "")))
		return
	var result = reply.data.get("strike", {})
	if typeof(result) == TYPE_DICTIONARY and result.get("ok") == false:
		game.ui.notify(str(result.get("reason", "")))
		return
	var animation := "throw" if throw else str(spec.get("animation", "punch"))
	game.player_visual.play_attack(animation, float(spec.get("windup_ms", 400)), hand)
	seen_swings["player:" + hand] = int(game.run_state.get("sim_time_ms", 0))
	game._accept_state(reply.data.state)


## Hold F with a shield: it comes up facing the way you face; let go and it comes down.
func guard(raised: bool) -> void:
	if raised == guarding or not game.gameplay_active:
		return
	var hand := shield_hand()
	if raised and hand.is_empty():
		return
	guarding = raised
	game.player_visual.set_guard(raised, hand if not hand.is_empty() else "left")
	var facing: Vector2 = [Vector2.DOWN, Vector2.LEFT, Vector2.UP, Vector2.RIGHT, Vector2(1, 1), Vector2(-1, 1),
		Vector2(-1, -1), Vector2(1, -1)][game.facing_row]
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/guard" % game.run_state.run_id, {
		"raised": raised, "facing": [facing.x, facing.y], "expected_version": game.run_state.event_seq,
		"request_id": game._request_id("guard")})
	if reply.ok:
		game._accept_state(reply.data.state)


## X: what's in each hand changes places.
func swap() -> void:
	if busy or not game.gameplay_active:
		return
	busy = true
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/swap" % game.run_state.run_id, {
		"expected_version": game.run_state.event_seq, "request_id": game._request_id("swap")})
	busy = false
	if reply.ok:
		var result = reply.data.get("swap", {})
		if typeof(result) == TYPE_DICTIONARY and result.get("ok") == false:
			game.ui.notify(str(result.get("reason", "")))
		game._accept_state(reply.data.state)


## Put something on or in a hand (slot), or take it off (slot ""); used by the Pack & gear screen.
func equip(object_id: String, slot: String) -> Dictionary:
	var body := {"object_id": object_id, "expected_version": game.run_state.event_seq,
		"request_id": game._request_id("equip")}
	if not slot.is_empty():
		body["slot"] = slot
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/equip" % game.run_state.run_id, body)
	if not reply.ok:
		return {"ok": false, "reason": "Could not do that just now."}
	game._accept_state(reply.data.state)
	return reply.data.get("equip", {})


func treat(object_id: String, condition: int, patient := "player") -> Dictionary:
	var reply: Dictionary = await game._api(HTTPClient.METHOD_POST, "/runs/%s/treat" % game.run_state.run_id, {
		"object_id": object_id, "condition": condition, "patient_id": patient,
		"expected_version": game.run_state.event_seq, "request_id": game._request_id("treat")})
	if not reply.ok:
		return {"ok": false, "reason": "Could not do that just now."}
	game._accept_state(reply.data.state)
	return reply.data.get("treat", {})


## Whoever you face within this range (the nearest attacker in a fight), else "".
func _aim(range_cells: float) -> String:
	var ahead: Vector2 = [Vector2.DOWN, Vector2.LEFT, Vector2.UP, Vector2.RIGHT, Vector2(1, 1), Vector2(-1, 1),
		Vector2(-1, -1), Vector2(1, -1)][game.facing_row]
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
		if toward.length() < best and (toward.length() < 8.0 or toward.normalized().dot(ahead.normalized()) > 0.3):
			best = toward.length()
			target = str(npc.id)
	return target


# --- Showing it -------------------------------------------------------------------------------------------------

## After every new state: what everyone holds and wears, blows winding up, things in flight.
func sync() -> void:
	var state: Dictionary = game.run_state
	if state.is_empty():
		return
	_sync_player_gear(state)
	var fight = state.get("fight")
	if typeof(fight) == TYPE_DICTIONARY:
		for who in fight.get("swings", {}):
			var swing: Dictionary = fight.swings[who]
			var key := int(swing.get("started", 0))
			if seen_swings.get(who, -1) == key:
				continue
			seen_swings[who] = key
			var painted: Node = game.get_node_or_null("NPCs/%s/PaintedActor" % who)
			if painted:
				painted.play_attack(str(swing.get("animation", "punch")), float(swing.lands_at) - float(swing.started))
	for hand in state.get("player", {}).get("swings", {}):
		var swing: Dictionary = state.player.swings[hand]
		var key := int(swing.get("started", 0))
		if seen_swings.get("player:" + hand, -1) != key:
			seen_swings["player:" + hand] = key
			game.player_visual.play_attack(str(swing.get("animation", "punch")),
				float(swing.lands_at) - float(swing.started), hand)
	for shot in state.get("projectiles", []):
		if seen_shots.has(shot.id):
			continue
		seen_shots[shot.id] = true
		var flying := Projectile.new()
		flying.from = game._cell_center(int(shot.from[0]), int(shot.from[1])) + Vector2(0, -40)
		flying.to = game._cell_center(int(shot.to[0]), int(shot.to[1])) + Vector2(0, -36)
		flying.flight_s = maxf(0.1, (float(shot.lands_at) - float(shot.launched_at)) / 1000.0)
		var profile: Dictionary = shot.get("profile", {})
		flying.kind = "arrow" if str(profile.get("ammo", "")) == "arrow" else "stone" if profile.get("ammo") else "thrown"
		if shot.get("object_id") != null:
			flying.texture = game.texture_for(state.objects.get(str(shot.object_id), {"id": str(shot.object_id)}))
		game.add_child(flying)


func _sync_player_gear(state: Dictionary) -> void:
	var player: Dictionary = state.get("player", {})
	var holding := {}
	var right := in_hand(player, "right")
	var left := in_hand(player, "left")
	for hand in ["right", "left"]:
		var obj := right if hand == "right" else left
		if obj.is_empty() or (hand == "left" and not right.is_empty() and str(right.id) == str(obj.id)):
			continue
		var spec := weapon_spec(obj)
		var kind := str(obj.get("gear", {}).get("kind", "")) if typeof(obj.get("gear")) == TYPE_DICTIONARY else ""
		var texture: Texture2D = null
		if obj.get("held_asset_id"):
			texture = _view_texture(str(obj.held_asset_id), true)
		if texture == null:
			texture = game.texture_for(obj)
		holding[hand] = {"texture": texture, "animation": str(spec.get("animation", "slash")), "kind": kind,
			"length_m": float(obj.length_m) if obj.get("length_m") != null else maxf(0.25, sqrt(float(obj.get("mass_kg", 0.5))) * 0.5)}
	var wearing := {}
	var kit = player.get("equipped")
	if typeof(kit) == TYPE_DICTIONARY:
		for slot in ["head", "body", "legs", "feet"]:
			var obj := in_hand(player, slot)
			if obj.is_empty() or obj.get("no_overlay", false) or not obj.get("worn_asset_id"):
				continue
			var sheet = _view_image(str(obj.worn_asset_id))
			if sheet != null:
				wearing[slot] = sheet
	game.player_visual.set_gear(holding, wearing)
	var guard_state = player.get("guard")
	var raised: bool = typeof(guard_state) == TYPE_DICTIONARY and guard_state.get("raised", false)
	if raised != guarding and not Input.is_key_pressed(KEY_F):
		guarding = raised
	game.player_visual.set_guard(raised or guarding, shield_hand() if not shield_hand().is_empty() else "left")


func _view_texture(asset_id: String, trim: bool) -> Texture2D:
	var image = _view_image(asset_id)
	if image == null:
		return null
	if not view_images.has(asset_id + ":texture"):
		var copy: Image = image.duplicate()
		if trim:
			var used: Rect2i = preload("res://scripts/painted_actor.gd").solid_rect(copy)
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
		var reply: Dictionary = await game._fetch_asset(asset_id)
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
