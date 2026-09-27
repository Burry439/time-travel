extends SceneTree

func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var scene: Node2D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	scene._apply_building_geometry(3)
	await physics_frame
	var player: CharacterBody2D = scene.player
	for name in ["Smithy", "Inn", "Carpenter", "Wagon", "EastWorkshop", "SouthHouse"]:
		var building: StaticBody2D = scene.get_node("BuildingCollision/" + name)
		var shape: RectangleShape2D = building.get_node("CollisionShape2D").shape
		var half := shape.size * 0.5
		var approaches := [
			[Vector2(building.position.x, building.position.y - half.y - 20.0), Vector2.DOWN],
			[Vector2(building.position.x, building.position.y + half.y + 20.0), Vector2.UP],
			[Vector2(building.position.x - half.x - 20.0, building.position.y), Vector2.RIGHT],
			[Vector2(building.position.x + half.x + 20.0, building.position.y), Vector2.LEFT]
		]
		for approach in approaches:
			player.position = approach[0]
			await physics_frame
			var contact: KinematicCollision2D = player.move_and_collide(approach[1] * 60.0)
			if contact == null or contact.get_collider() != building:
				push_error("Player passed through %s from %s" % [name, approach[1]])
				quit(1)
				return
	# Old journeys retain the footprint they were created with.
	scene._apply_building_geometry(2)
	var old_inn: RectangleShape2D = scene.get_node("BuildingCollision/Inn/CollisionShape2D").shape
	if old_inn.size != Vector2(416, 128):
		push_error("Legacy inn footprint changed")
		quit(1)
		return
	print("BUILDING EDGE PASS: 24 approach directions blocked; legacy footprint preserved")
	quit(0)
