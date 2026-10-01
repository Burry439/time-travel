extends Node
## Pictures for things: authored art, committed material art, a painting fetched from the service
## (polled until it's ready), or a loading ring meanwhile. Never another thing's picture.

var game: Node2D # The game (scripts/main.gd), whose child this is.


# Objects without authored art show a loading ring until their painting arrives (loading_ring.gd).
const OBJECT_HEIGHT := 46.0


const OBJECT_MAX_WIDTH := 60.0


var object_textures: Dictionary = {} # object id -> resolved Texture2D


var sprite_state: Dictionary = {} # asset id -> "polling" | "failed"


## Picture for any object: authored node, committed material art, painted sprite, or placeholder.
func texture_for(obj: Dictionary) -> Texture2D:
	var id := str(obj["id"])
	if object_textures.has(id):
		return object_textures[id]
	var authored := game.get_node_or_null("M2Objects/" + id) as Sprite2D
	if authored and not authored.has_meta("dynamic"):
		return authored.texture
	if obj.has("scene_node"):
		var scene_art := game.get_node_or_null(str(obj["scene_node"])) as Sprite2D
		if scene_art:
			return scene_art.texture
	var material_art := "res://assets/generated/materials/%s.png" % id
	if ResourceLoader.exists(material_art):
		object_textures[id] = _trimmed((load(material_art) as Texture2D).get_image())
		return object_textures[id]
	var asset_id := str(obj.get("sprite_asset_id", ""))
	var cached := "user://assets/%s.png" % asset_id
	if not asset_id.is_empty() and FileAccess.file_exists(cached):
		var image := Image.load_from_file(cached)
		if image:
			object_textures[id] = _trimmed(image)
			return object_textures[id]
	if not asset_id.is_empty() and not sprite_state.has(asset_id):
		_poll(id, asset_id)
	return null # Not painted yet (or it couldn't be): callers show a loading ring, never another object's art.


func is_placeholder(obj: Dictionary) -> bool:
	if obj.has("scene_node"):
		return false
	var authored := game.get_node_or_null("M2Objects/" + str(obj["id"])) as Sprite2D
	return not object_textures.has(str(obj["id"])) and not (authored and not authored.has_meta("dynamic"))


func sprite_status(obj: Dictionary) -> String:
	if not is_placeholder(obj):
		return "ready"
	var asset_id := str(obj.get("sprite_asset_id", ""))
	return "none" if asset_id.is_empty() else str(sprite_state.get(asset_id, "polling"))


func _trimmed(image: Image) -> Texture2D:
	var started := Time.get_ticks_usec()
	var texture := _trimmed_now(image)
	game._prof("trim_texture", started)
	return texture


func _trimmed_now(image: Image) -> Texture2D:
	if image.is_compressed():
		image.decompress()
	var used := image.get_used_rect()
	if used.size.x > 0 and used.size.y > 0:
		image = image.get_region(used)
	var longest := maxi(image.get_width(), image.get_height())
	if longest > 256:
		var ratio := 256.0 / float(longest)
		image.resize(maxi(1, roundi(image.get_width() * ratio)), maxi(1, roundi(image.get_height() * ratio)),
			Image.INTERPOLATE_LANCZOS)
	return ImageTexture.create_from_image(image)


func apply_to(sprite: Sprite2D, obj: Dictionary) -> void:
	var texture := texture_for(obj)
	var ring := sprite.get_node_or_null("LoadingRing")
	if texture == null:
		sprite.texture = null
		sprite.scale = Vector2.ONE
		if ring == null:
			ring = preload("res://scripts/loading_ring.gd").new()
			ring.name = "LoadingRing"
			sprite.add_child(ring)
		ring.missing = sprite_status(obj) in ["failed", "none"]
		ring.queue_redraw()
		return
	if ring:
		sprite.remove_child(ring)
		ring.queue_free()
	if sprite.texture == texture:
		return
	sprite.texture = texture
	var size := texture.get_size()
	# Trees stand tall and heavy things read larger; everyday items share one small size.
	var big := 104.0 if float(obj.get("mass_kg", 0.0)) >= 300.0 else 64.0 # A cart or an ox reads bigger than a trough.
	var height := 150.0 if str(obj.get("feature", "")) == "tree" else OBJECT_HEIGHT if "carry" in obj.capabilities else big
	var width := height * 1.3 if height > OBJECT_HEIGHT else OBJECT_MAX_WIDTH
	sprite.scale = Vector2.ONE * minf(height / size.y, width / size.x)
	# Tall things stand on their cell (so a tree falls from its base); small items stay centred.
	sprite.offset = Vector2.ZERO if height == OBJECT_HEIGHT else Vector2(0, -size.y * 0.5 + 12.0 / sprite.scale.y)


## Painting happens on the backend after the object exists; poll until it's ready.
func _poll(object_id: String, asset_id: String) -> void:
	sprite_state[asset_id] = "polling"
	for _attempt in 60:
		var reply: Dictionary = await game.net.fetch_asset(asset_id)
		if game.run_state.is_empty():
			break
		if reply.status == 200:
			var image := Image.new()
			if image.load_png_from_buffer(reply.body) == OK:
				DirAccess.make_dir_recursive_absolute("user://assets")
				image.save_png("user://assets/%s.png" % asset_id)
				object_textures[object_id] = _trimmed(image)
				sprite_state.erase(asset_id)
				refresh()
				return
		if reply.status != 202:
			sprite_state[asset_id] = "failed" # Keep the placeholder; developer mode can retry.
			if game.run_state.get("mode", "") == "developer":
				game.ui.notify("Sprite for %s could not be painted (HTTP %s). See AI traces (F3)." % [object_id, reply.status])
			return
		await get_tree().create_timer(3.0).timeout
	sprite_state.erase(asset_id) # Gave up for now; the next display refresh polls again.


func refresh() -> void:
	if game.run_state.is_empty():
		return
	game.view.sync()
	game.ui.refresh_icons()


func retry(asset_id: String) -> void:
	var path: String = game.run_path("/assets/" + asset_id + "/retry")
	var reply: Dictionary = await game.net.api(HTTPClient.METHOD_POST, path)
	if reply.ok:
		sprite_state.erase(asset_id)
		refresh()
		game.ui.notify("Repainting the sprite…")
