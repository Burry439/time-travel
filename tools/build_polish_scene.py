"""Author editor-visible presentation nodes and collisions from the shared map data.

Does not regenerate or edit image pixels. AtlasTexture regions use the generated PNG.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
scene_path = ROOT / "scenes/main.tscn"
text = scene_path.read_text(encoding="utf-8-sig")
# Keep this authoring utility repeatable.
text = re.sub(r'\n; POLISH RESOURCES.*?; END POLISH RESOURCES\n', '\n', text, flags=re.S)
text = re.sub(r'\n; POLISH NODES.*', '', text, flags=re.S)
resources = '''
; POLISH RESOURCES
[ext_resource type="Script" path="res://scripts/actor_presence.gd" id="24_presence"]
[ext_resource type="Script" path="res://scripts/landscape.gd" id="25_landscape"]
[ext_resource type="Texture2D" path="res://assets/generated/village_foliage.png" id="26_foliage"]
[ext_resource type="Shader" path="res://assets/ground_finish.gdshader" id="27_ground_shader"]
[ext_resource type="Texture2D" path="res://assets/source/generated/grass_source.png" id="28_grass"]
[ext_resource type="Shader" path="res://assets/foliage_sway.gdshader" id="29_sway"]

[sub_resource type="ShaderMaterial" id="FoliageSway"]
shader = ExtResource("29_sway")

[sub_resource type="ShaderMaterial" id="GroundFinish"]
shader = ExtResource("27_ground_shader")
shader_parameter/ground_source = ExtResource("28_grass")
'''
# Generated atlas was visually checked: trees occupy the upper 800 pixels.
for name, rect in {
    "oak": (0, 0, 704, 800), "cypress": (704, 0, 576, 800),
    "shrub": (0, 816, 680, 464), "rocks": (680, 816, 600, 464),
}.items():
    resources += f'\n[sub_resource type="AtlasTexture" id="Atlas_{name}"]\natlas = ExtResource("26_foliage")\nregion = Rect2{rect}\n'

geometry_path = ROOT / "data/world_geometry.json"
geometry = json.loads(geometry_path.read_text())
trees = [(10, 65), (32, 64), (59, 65), (73, 63), (88, 66), (13, 53), (58, 54),
         (85, 50), (8, 40), (31, 38), (62, 40), (88, 38), (8, 29), (35, 28),
         (87, 22), (29, 16), (65, 16), (8, 16), (84, 12)]
geometry["obstacles"] = [{"name": f"Tree{i:02}", "cells": [x, y, 1, 1]} for i, (x, y) in enumerate(trees)]
geometry_path.write_text(json.dumps(geometry, indent=2) + "\n")
for item in geometry["buildings"] + geometry["obstacles"]:
    _, _, w, h = item["cells"]
    resources += f'\n[sub_resource type="RectangleShape2D" id="Foot_{item["name"]}"]\nsize = Vector2({w*32}, {h*32})\n'
resources += '; END POLISH RESOURCES\n'
index = text.index('[sub_resource ')
text = text[:index] + resources + text[index:]

def set_node(name, parent, props):
    global text
    pattern = r'(\[node name="' + name + r'"[^\n]*' + (r'parent="' + re.escape(parent) + '"' if parent else '') + r'[^\n]*\]\n)(.*?)(?=\n\[|\Z)'
    match = re.search(pattern, text, re.S)
    if not match:
        raise ValueError(f"Missing node {name}")
    body = match[2]
    for key, value in props.items():
        body = re.sub(r'^' + re.escape(key) + r' = .*\n?', '', body, flags=re.M)
        body += f'{key} = {value}\n'
    text = text[:match.start()] + match[1] + body + text[match.end():]

for node, parent in [("Main", ""), ("Map", "."), ("M2Objects", "."), ("NPCPreview", ".")]:
    set_node(node, parent, {"y_sort_enabled": "true"})
set_node("Ground", "Map", {"z_index": "-20", "modulate": "Color(1, 1, 1, 1)", "material": 'SubResource("GroundFinish")'})
for name, x, y, scale, half in [
    ("Smithy", 560, 785, 1.5, 126), ("Inn", 1104, 1590, 0.48, 503),
    ("Carpenter", 2050, 822, 1.5, 126), ("Wagon", 2580, 956, 1.35, 85),
    ("EastWorkshop", 2380, 1225, 1.3, 126), ("SouthHouse", 866, 1940, 1.25, 126),
]:
    set_node(name, "Map", {"position": f"Vector2({x}, {y})", "offset": f"Vector2(0, -{half})", "scale": f"Vector2({scale}, {scale})"})
set_node("Inn", "Map", {"texture": 'ExtResource("31_inn_painted")'})
set_node("Player", ".", {"motion_mode": "1"})
set_node("Camera2D", "Player", {"position_smoothing_speed": "12.0"})
text += '''
; POLISH NODES
[node name="RoadsAndGrass" type="Node2D" parent="Map"]
z_index = -19
script = ExtResource("25_landscape")

[node name="Shadow" type="Node2D" parent="Player"]
show_behind_parent = true
script = ExtResource("24_presence")

[node name="BuildingCollision" type="Node2D" parent="."]
'''
for item in geometry["buildings"] + geometry["obstacles"]:
    name = item["name"]
    x, y, w, h = item["cells"]
    text += f'''
[node name="{name}" type="StaticBody2D" parent="BuildingCollision"]
position = Vector2({(x+w/2)*32}, {(y+h/2)*32})

[node name="CollisionShape2D" type="CollisionShape2D" parent="BuildingCollision/{name}"]
shape = SubResource("Foot_{name}")
'''
text += '\n[node name="Foliage" type="Node2D" parent="."]\ny_sort_enabled = true\n'
for i, (x, y) in enumerate(trees):
    kind = 'cypress' if i % 3 == 0 else 'oak'
    scale = 0.38 if kind == 'cypress' else 0.42
    text += f'''
[node name="Tree{i:02}" type="Sprite2D" parent="Foliage"]
material = SubResource("FoliageSway")
position = Vector2({x*32+16}, {y*32+16})
scale = Vector2({scale}, {scale})
texture = SubResource("Atlas_{kind}")
offset = Vector2(0, -350)
texture_filter = 2

[node name="Shadow" type="Node2D" parent="Foliage/Tree{i:02}"]
show_behind_parent = true
script = ExtResource("24_presence")
radius = 80.0
'''
for i, (x, y) in enumerate([(1300,2180),(1780,2090),(1240,1940),(1790,1820),(1270,1780),
    (1840,1470),(780,1710),(965,1620),(890,850),(1830,860),(2710,1050),(1360,660),
    (1760,560),(1910,400),(1070,380),(420,1030),(2300,1500),(560,2130),(2740,1960)]):
    kind = 'rocks' if i % 4 == 0 else 'shrub'
    scale = 0.14 if kind == 'rocks' else 0.18
    text += f'''
[node name="Detail{i:02}" type="Sprite2D" parent="Foliage"]
material = SubResource("FoliageSway")
position = Vector2({x}, {y})
scale = Vector2({scale}, {scale})
texture = SubResource("Atlas_{kind}")
offset = Vector2(0, -180)
texture_filter = 2
'''
# A physical sign makes the main route legible without a screen-filling compass.
text += '''
[node name="RoadSign" type="Node2D" parent="Map"]
position = Vector2(1745, 1950)

[node name="Post" type="Polygon2D" parent="Map/RoadSign"]
polygon = PackedVector2Array(-4, 0, 4, 0, 4, -100, -4, -100)
color = Color(0.27, 0.20, 0.12, 1)

[node name="Board" type="Polygon2D" parent="Map/RoadSign"]
polygon = PackedVector2Array(-54, -95, 44, -95, 57, -77, 44, -59, -54, -59)
color = Color(0.38, 0.28, 0.15, 1)

[node name="Label" type="Label" parent="Map/RoadSign"]
offset_left = -44.0
offset_top = -88.0
text = "CITY  ↑"
theme_override_colors/font_color = Color(0.91, 0.83, 0.64, 1)
theme_override_font_sizes/font_size = 18
'''
count = len(re.findall(r'^\[(?:ext_resource|sub_resource) ', text, re.M)) + 1
text = re.sub(r'load_steps=\d+', f'load_steps={count}', text)
scene_path.write_text(text, encoding="utf-8")
print(f"Authored scene with {len(trees)} trees and {len(geometry['buildings'])} building footprints")
