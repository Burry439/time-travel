@tool
extends Node2D
## Editor-visible cutout rig. Every layer samples the original painted atlas;
## no generated pixels are modified or re-exported.

const TRAVELER := preload("res://assets/generated/traveler_painted_turnaround.png")
const TRAVELER_DIAGONALS := preload("res://assets/generated/traveler_painted_diagonals.png")
const HESSA := preload("res://assets/generated/hessa_painted_turnaround.png")
const CAST_ART := {
	"roderic": preload("res://assets/generated/roderic_painted_turnaround.png"),
	"bren": preload("res://assets/generated/bren_painted_turnaround.png"),
	"oren": preload("res://assets/generated/oren_painted_turnaround.png"),
	"mara": preload("res://assets/generated/mara_painted_turnaround.png"),
	"jory": preload("res://assets/generated/jory_painted_turnaround.png"),
	"tomas": preload("res://assets/generated/tomas_painted_turnaround.png"),
	"darin": preload("res://assets/generated/darin_painted_turnaround.png"),
	"elin": preload("res://assets/generated/elin_painted_turnaround.png"),
	"kade": preload("res://assets/generated/kade_painted_turnaround.png")
}

@export_enum("traveler", "hessa", "roderic", "bren", "oren", "mara", "jory", "tomas", "darin", "elin", "kade") var actor_id := "traveler":
	set(value):
		actor_id = value
		if is_inside_tree():
			_build()

@export_range(80.0, 140.0, 1.0) var height_px := 108.0:
	set(value):
		height_px = value
		if is_inside_tree():
			_build()

var views: Array[Node2D] = []
var joints: Array[Dictionary] = []
var rest_positions: Array[Dictionary] = []
var facing := 0
var locomotion := "idle"
var stride_phase := 0.0
var pose_clock := 0.0
var gesture_time := 0.0
var gesture_kind := ""
var dead := false

const BOUNDS := {
	"traveler": [Rect2i(222, 49, 258, 573), Rect2i(831, 58, 151, 562),
		Rect2i(223, 647, 255, 541), Rect2i(835, 650, 138, 548)],
	"hessa": [Rect2i(174, 43, 305, 588), Rect2i(785, 59, 250, 578),
		Rect2i(181, 681, 299, 568), Rect2i(785, 685, 241, 571)],
	"roderic": [Rect2i(192,31,299,589), Rect2i(771,36,229,586), Rect2i(172,660,303,593), Rect2i(805,660,231,600)],
	"bren": [Rect2i(195,32,284,605), Rect2i(786,35,191,604), Rect2i(208,662,274,592), Rect2i(816,664,172,600)],
	"oren": [Rect2i(212,36,269,597), Rect2i(830,42,155,600), Rect2i(215,665,274,586), Rect2i(850,670,147,591)],
	"mara": [Rect2i(196,33,293,611), Rect2i(809,46,203,601), Rect2i(180,662,297,584), Rect2i(822,672,191,587)],
	"jory": [Rect2i(201,31,257,616), Rect2i(814,38,159,610), Rect2i(210,664,259,605), Rect2i(826,673,144,596)],
	"tomas": [Rect2i(196,28,285,600), Rect2i(801,31,198,604), Rect2i(202,661,290,588), Rect2i(814,661,191,604)],
	"darin": [Rect2i(199,41,270,591), Rect2i(804,42,183,592), Rect2i(198,668,291,575), Rect2i(820,668,182,590)],
	"elin": [Rect2i(236,33,241,605), Rect2i(824,37,148,607), Rect2i(240,672,236,581), Rect2i(838,675,150,593)],
	"kade": [Rect2i(189,31,292,612), Rect2i(819,31,181,613), Rect2i(191,660,292,601), Rect2i(817,661,166,613)]
}
const DIAGONAL_BOUNDS := [
	Rect2i(225, 47, 256, 582),  # southeast: front and right side
	Rect2i(794, 53, 237, 576),  # southwest: front and left side
	Rect2i(246, 635, 234, 568), # northwest: back and left side
	Rect2i(783, 636, 243, 564)  # northeast: back and right side
]
# The painted NPC atlases put right-facing at the top right; the traveler differs.
const TRAVELER_ORDER := [0, 1, 2, 3]
const CAST_ORDER := [0, 3, 2, 1]
const GAIT_LENGTH := {
	"traveler": 1.0, "hessa": 0.94, "roderic": 1.12, "bren": 1.03,
	"oren": 1.07, "mara": 0.96, "jory": 0.89, "tomas": 1.08,
	"darin": 1.04, "elin": 0.91, "kade": 1.06
}


func _ready() -> void:
	pose_clock = fposmod(float(actor_id.hash() % 628) / 100.0, TAU)
	stride_phase = pose_clock
	_build()
	set_motion(0, "idle", 0.0, 0.0)


func _build() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()
	views.clear()
	joints.clear()
	rest_positions.clear()
	var view_count := 8 if actor_id == "traveler" else 4
	for row in view_count:
		var atlas: Texture2D = TRAVELER_DIAGONALS if row >= 4 else TRAVELER if actor_id == "traveler" else HESSA if actor_id == "hessa" else CAST_ART[actor_id]
		var atlas_order := TRAVELER_ORDER if actor_id == "traveler" else CAST_ORDER
		var box: Rect2i = DIAGONAL_BOUNDS[row - 4] if row >= 4 else BOUNDS[actor_id][atlas_order[row]]
		var whole := Node2D.new()
		whole.name = ["Front", "Left", "Back", "Right", "Southeast", "Southwest", "Northwest", "Northeast"][row]
		whole.visible = row == facing
		add_child(whole)
		views.append(whole)
		var center := Vector2(box.position.x + box.size.x * 0.5, box.end.y)
		var rig_scale := height_px / float(box.size.y)
		whole.scale = Vector2.ONE * rig_scale
		var rig: Dictionary = {}
		var rests: Dictionary = {}
		# Overlaps are intentional, keeping painted seams hidden at the rest pose.
		# Anatomy differs by view; each part has its own shoulder/hip pivot.
		var slices := {
			"hip_bridge": Rect2(0.34, 0.53, 0.32, 0.34),
			"left_leg": Rect2(0.06, 0.57, 0.47, 0.43),
			"right_leg": Rect2(0.47, 0.57, 0.47, 0.43),
			"torso": Rect2(0.15, 0.19, 0.70, 0.51),
			"left_arm": Rect2(0.00, 0.22, 0.28, 0.46),
			"right_arm": Rect2(0.72, 0.22, 0.28, 0.46),
			"head": Rect2(0.18, 0.00, 0.64, 0.27)
		}
		for part_name in ["hip_bridge", "left_leg", "right_leg", "torso", "left_arm", "right_arm", "head"]:
			var area: Rect2 = slices[part_name]
			var region := Rect2i(
				box.position.x + roundi(box.size.x * area.position.x),
				box.position.y + roundi(box.size.y * area.position.y),
				ceili(box.size.x * area.size.x),
				ceili(box.size.y * area.size.y))
			var pivot := Node2D.new()
			pivot.name = part_name.to_pascal_case()
			var joint: Vector2 = Vector2(region.position)
			if part_name == "hip_bridge":
				joint += Vector2(region.size.x * 0.5, region.size.y * 0.1)
			elif part_name == "left_leg" or part_name == "right_leg":
				joint += Vector2(region.size.x * 0.5, region.size.y * 0.05)
			elif part_name == "head":
				joint += Vector2(region.size.x * 0.5, region.size.y * 0.85)
			else:
				joint += Vector2(region.size.x * (0.82 if part_name == "left_arm" else 0.18 if part_name == "right_arm" else 0.5), region.size.y * 0.12)
			pivot.position = joint - center
			whole.add_child(pivot)
			var section := Sprite2D.new()
			section.name = "Art"
			var texture := AtlasTexture.new()
			texture.atlas = atlas
			texture.region = Rect2(region)
			section.texture = texture
			section.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
			section.position = Vector2(region.position) + Vector2(region.size) * 0.5 - joint
			pivot.add_child(section)
			rig[part_name] = pivot
			rests[part_name] = pivot.position
		joints.append(rig)
		rest_positions.append(rests)
	queue_redraw()


func set_motion(row: int, mode: String, distance: float, delta: float) -> void:
	if views.is_empty() or dead:
		return
	facing = clampi(row, 0, views.size() - 1)
	locomotion = mode
	pose_clock += delta
	if mode == "walk" or mode == "run":
		stride_phase += distance * TAU / ((96.0 if mode == "walk" else 118.0) * float(GAIT_LENGTH[actor_id]))
	for i in views.size():
		views[i].visible = i == facing
	var rig: Dictionary = joints[facing]
	var active := mode == "walk" or mode == "run"
	var leg_swing := sin(stride_phase) * (0.10 if mode == "walk" else 0.15) if active else 0.0
	if actor_id == "hessa":
		leg_swing *= 0.48
	var sway := sin(pose_clock * 1.5) * 0.012
	var gesture := 0.0
	if gesture_time > 0.0:
		gesture_time = maxf(0.0, gesture_time - delta)
		gesture = sin((1.0 - gesture_time / 0.48) * PI) * 0.24
		if gesture_kind == "pickup":
			gesture *= -1.0
	for part_name in rig:
		var pivot: Node2D = rig[part_name]
		pivot.rotation = 0.0
		pivot.scale = Vector2.ONE
		pivot.position = rest_positions[facing][part_name]
	if active:
		if facing == 1 or facing == 3:
			var forward := -1.0 if facing == 1 else 1.0
			var swing := cos(stride_phase) * (0.20 if mode == "run" else 0.15)
			rig["left_leg"].rotation = swing * forward
			rig["right_leg"].rotation = -swing * forward
		else:
			rig["left_leg"].rotation = leg_swing
			rig["right_leg"].rotation = -leg_swing
			var depth := sin(stride_phase) * (5.0 if mode == "run" else 3.0) / views[facing].scale.y
			rig["left_leg"].position.y += depth
			rig["right_leg"].position.y -= depth
		rig["left_arm"].rotation = -leg_swing * 0.55
		rig["right_arm"].rotation = leg_swing * 0.55
	rig["head"].rotation = sway * 0.45
	rig["torso"].rotation = sway
	if mode == "work":
		rig["left_arm"].rotation = sin(pose_clock * 6.0) * 0.13
		rig["right_arm"].rotation = -sin(pose_clock * 6.0) * 0.21
		rig["torso"].rotation += sin(pose_clock * 6.0) * 0.018
	elif mode == "look" or mode == "patrol":
		rig["head"].rotation += sin(pose_clock * 1.15) * 0.055
	elif mode == "conversation":
		rig["right_arm"].rotation = sin(pose_clock * 3.0) * 0.16
	rig["right_arm"].rotation += gesture
	var bob := absf(sin(stride_phase)) * (0.9 if mode == "walk" else 1.8) if active else sin(pose_clock * 1.5) * 0.25
	for part_name in ["head", "left_arm", "right_arm", "torso"]:
		var pivot: Node2D = rig[part_name]
		pivot.position.y = (rest_positions[facing][part_name] as Vector2).y - bob / views[facing].scale.y
	if gesture_time > 0.0 and gesture_kind == "pickup":
		for part_name in ["head", "left_arm", "right_arm", "torso"]:
			var pivot: Node2D = rig[part_name]
			pivot.position.y += gesture * 10.0


func play_gesture(kind: String) -> void:
	gesture_kind = kind
	gesture_time = 0.48


## A struck recoil: a red flash and a short shove away from the blow.
func hurt(from_direction := 1.0) -> void:
	if dead:
		return
	var tween := create_tween()
	tween.tween_property(self, "modulate", Color(1.0, 0.45, 0.4), 0.06)
	tween.parallel().tween_property(self, "position:x", position.x + 6.0 * from_direction, 0.06)
	tween.tween_property(self, "modulate", Color.WHITE, 0.35)
	tween.parallel().tween_property(self, "position:x", position.x, 0.25)


## Collapse sideways around the feet and stay down.
func die(fall_direction := 1.0) -> void:
	if dead:
		return
	dead = true
	_hold_still()
	var tween := create_tween()
	tween.tween_property(self, "modulate", Color(1.0, 0.5, 0.45), 0.08)
	tween.tween_property(self, "rotation", fall_direction * 0.35, 0.18).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "rotation", fall_direction * PI * 0.47, 0.42) \
		.set_trans(Tween.TRANS_BOUNCE).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(self, "modulate", Color(0.62, 0.6, 0.58), 0.6)


## Restore a body that died earlier in the journey without replaying the fall.
func lie_dead(fall_direction := 1.0) -> void:
	dead = true
	_hold_still()
	rotation = fall_direction * PI * 0.47
	modulate = Color(0.62, 0.6, 0.58)


func _hold_still() -> void:
	if joints.is_empty():
		return
	for part_name in joints[facing]:
		var pivot: Node2D = joints[facing][part_name]
		pivot.rotation = 0.0
		pivot.position = rest_positions[facing][part_name]


