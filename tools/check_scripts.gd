extends SceneTree
## Compile every GDScript in the project in one Godot run (tools/check.ps1): a script that doesn't parse fails the
## check. Faster than one --check-only per file.
##   Godot --headless --path . --script res://tools/check_scripts.gd

const ROOTS := ["res://scripts", "res://tools"]


func _initialize() -> void:
	var failed: PackedStringArray = []
	var checked := 0
	for root_dir in ROOTS:
		for path in _scripts(root_dir):
			checked += 1
			var script := load(path) as GDScript
			if script == null or not script.can_instantiate():
				failed.append(path)
	if failed.is_empty():
		print("CHECK SCRIPTS PASSED: %d scripts compile" % checked)
		quit(0)
	else:
		push_error("CHECK SCRIPTS FAILED: " + ", ".join(failed))
		quit(1)


func _scripts(dir_path: String) -> PackedStringArray:
	var found: PackedStringArray = []
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return found
	for file in dir.get_files():
		if file.ends_with(".gd"):
			found.append(dir_path.path_join(file))
	for sub in dir.get_directories():
		found.append_array(_scripts(dir_path.path_join(sub)))
	return found
