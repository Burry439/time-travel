extends SceneTree
## Trims and shrinks the committed world art (assets/generated/materials) to what the game shows: the used area,
## at most 256 px on its longest side, exactly as main.gd's _trimmed_texture does at runtime. Painted pictures
## arrive at 1024 px; trimming ~100 of them on entering a journey froze the first frame for seconds (D-52).
## Run after painting new art, then import:
##   Godot --headless --path . --script res://tools/shrink_material_art.gd
##   Godot --headless --path . --import
const LONGEST := 256


func _initialize() -> void:
	var folder := ProjectSettings.globalize_path("res://assets/generated/materials")
	var shrunk := 0
	for file in DirAccess.get_files_at(folder):
		if not file.ends_with(".png"):
			continue
		var path := folder.path_join(file)
		var image := Image.load_from_file(path)
		if image == null:
			continue
		if image.is_compressed():
			image.decompress()
		if maxi(image.get_width(), image.get_height()) <= LONGEST:
			continue # Done before: trimming again would shave its edge off a little more each time.
		var used := image.get_used_rect()
		var trimmed := used.size.x > 0 and used.size != image.get_size()
		if trimmed:
			image = image.get_region(used)
		var longest := maxi(image.get_width(), image.get_height())
		if longest > LONGEST:
			var ratio := float(LONGEST) / float(longest)
			image.resize(maxi(1, roundi(image.get_width() * ratio)), maxi(1, roundi(image.get_height() * ratio)),
				Image.INTERPOLATE_LANCZOS)
		if trimmed or longest > LONGEST:
			image.save_png(path)
			shrunk += 1
	print("SHRINK DONE: %d pictures trimmed and shrunk" % shrunk)
	quit(0)
