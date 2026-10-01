"""Build a level's map scene (GDD D-59) from its data, and paint its pieces in the village's style.

    backend/.venv/Scripts/python.exe tools/make_map.py <map_id> [--paint] [--force]

Reads data/maps/<map_id>.json and writes scenes/maps/<map_id>.tscn: the ground, each building and obstacle drawn
on its own cells (bottom edge on the footprint's), the trees under Foliage (where the game finds them by name),
and an empty M2Objects for the things lying about. Collisions come from the same data at runtime
(world_view.apply_building_geometry), so the picture and the grid can't disagree.

With --paint (needs OPENAI_API_KEY in backend/.env) it first asks the image model (MODEL_IMAGE) for what isn't
painted yet: the ground (map.art.ground) and each piece named in map.art.pieces, into assets/maps/<map_id>/.
Every building named Wall... is a band cut from one painting, "Wall" (the top one rising art.wall_rise cells
above the floor). A piece with no painting is drawn as a plain block, so a map is playable before its art exists.
Then:
    Godot --headless --path . --import
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ai import config  # noqa: E402

CELL = 32
STYLE = (
    "Style: detailed painterly pixel art with crisp edges, warm muted ochre and olive palette, sun from upper left, "
    "soft form shading, high-angle three-quarter top-down view, matching a grounded premodern village RPG."
)
GROUND = (
    "Top-down ground texture for a 2D RPG map, seen from high above: {ground}. Even lighting over the whole image, "
    "no buildings, no people, no furniture, no large objects, no text, no border, no vignette. {style}"
)
PIECE = (
    "2D RPG map piece for a grounded premodern village game: {piece}. The whole thing centred and fully visible, "
    "filling most of the frame, seen from a high three-quarter top-down angle so its front faces down the screen. "
    "Transparent background. Only the piece: no ground tile, no cast shadow, no people, no text, no border. {style}"
)
BLOCKS = {"indoor": "Color(0.29, 0.2, 0.13, 1)", "outdoor": "Color(0.42, 0.36, 0.25, 1)"}  # Unpainted pieces.
SURROUND = {"indoor": "Color(0.07, 0.06, 0.05, 1)", "outdoor": "Color(0.26, 0.31, 0.17, 1)"}
FOLIAGE = "res://assets/generated/village_foliage.png"  # The village's trees, for any tree with no painting.
OAK = "Rect2(0, 0, 704, 800)"


def _image(prompt: str, size: str, transparent: bool) -> bytes:
    response = config.client().images.generate(
        model=config.image_model(),
        prompt=prompt,
        size=size,
        quality="high",
        background="transparent" if transparent else "opaque",
        output_format="png",
        n=1,
    )
    return base64.b64decode(response.data[0].b64_json)


def paint(plan: dict, folder: Path, force: bool) -> None:
    art = plan.get("art") or {}
    folder.mkdir(parents=True, exist_ok=True)
    width, height = plan["size"][0] * CELL, plan["size"][1] * CELL
    ground = folder / "ground.png"
    if art.get("ground") and (force or not ground.exists()):
        print("painting the ground…", flush=True)
        raw = folder / "ground.raw.png"
        raw.write_bytes(_image(GROUND.format(ground=art["ground"], style=STYLE), "1536x1024", False))
        picture = Image.open(raw).convert("RGB")
        scale = max(width / picture.width, height / picture.height)  # Cover the map, then crop to it.
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)), Image.LANCZOS)
        left, top = (picture.width - width) // 2, (picture.height - height) // 2
        picture.crop((left, top, left + width, top + height)).save(ground)
        raw.unlink()
    for name, words in (art.get("pieces") or {}).items():
        target = folder / f"{name}.png"
        if target.exists() and not force:
            continue
        print(f"painting {name}…", flush=True)
        raw = folder / f"{name}.raw.png"
        raw.write_bytes(_image(PIECE.format(piece=words, style=STYLE), "1024x1024", True))
        picture = Image.open(raw).convert("RGBA")
        box = picture.getchannel("A").point(lambda value: 255 if value >= 64 else 0).getbbox()
        picture.crop(box).save(target)  # Trimmed to the piece itself.
        raw.unlink()


class Scene:
    """A .tscn written by hand: resources first, then nodes in tree order."""

    def __init__(self) -> None:
        self.resources: list[str] = []
        self.nodes: list[str] = []
        self.ids = 0

    def texture(self, path: str) -> str:
        self.ids += 1
        rid = f"{self.ids}_tex"
        self.resources.append(f'[ext_resource type="Texture2D" path="{path}" id="{rid}"]')
        return rid

    def atlas(self, texture: str, region: str) -> str:
        self.ids += 1
        rid = f"Atlas_{self.ids}"
        self.resources.append(f'[sub_resource type="AtlasTexture" id="{rid}"]\natlas = ExtResource("{texture}")\nregion = {region}')
        return rid

    def node(self, name: str, kind: str, parent: str | None, **props: str) -> None:
        head = f'[node name="{name}" type="{kind}"' + (f' parent="{parent}"' if parent else "") + "]"
        self.nodes.append("\n".join([head] + [f"{key} = {value}" for key, value in props.items()]))

    def text(self) -> str:
        exts = [r for r in self.resources if r.startswith("[ext")]
        subs = [r for r in self.resources if r.startswith("[sub")]
        return "\n\n".join([f"[gd_scene load_steps={len(self.resources) + 1} format=3]"] + exts + subs + self.nodes) + "\n"


def build(plan: dict, folder: Path) -> str:
    art = plan.get("art") or {}
    kind = art.get("kind", "outdoor")
    width, height = plan["size"][0] * CELL, plan["size"][1] * CELL
    scene = Scene()
    root = "".join(part.title() for part in plan["id"].split("_")) + "Map"
    scene.node(root, "Node2D", None, y_sort_enabled="true")
    scene.node("Map", "Node2D", ".", y_sort_enabled="true")
    pad = 1600
    scene.node("Surround", "ColorRect", "Map", z_index="-21", offset_left=f"{-pad}.0", offset_top=f"{-pad}.0",
               offset_right=f"{width + pad}.0", offset_bottom=f"{height + pad}.0", color=SURROUND[kind])
    if (folder / "ground.png").exists():
        ground = scene.texture(f"res://assets/maps/{plan['id']}/ground.png")
        scene.node("Ground", "Sprite2D", "Map", z_index="-20", texture_filter="1", centered="false",
                   texture=f'ExtResource("{ground}")')
    else:
        scene.node("Floor", "ColorRect", "Map", z_index="-20", offset_right=f"{width}.0", offset_bottom=f"{height}.0",
                   color="Color(0.45, 0.4, 0.28, 1)")
    trees = [item for item in plan["obstacles"] if item.get("tree")]
    wall = folder / "Wall.png"
    rise = art.get("wall_rise", 0)
    wall_texture = scene.texture(f"res://assets/maps/{plan['id']}/Wall.png") if wall.exists() else None
    for item in plan["buildings"] + [item for item in plan["obstacles"] if not item.get("tree")]:
        x, y, w, h = item["cells"]
        picture = folder / f"{item['name']}.png"
        if item["name"].startswith("Wall") and wall_texture:  # A band cut from the one wall painting.
            up = rise if y == 0 else 0  # The back wall stands up above the floor.
            scene.node(item["name"], "TextureRect", "Map", z_index="-19", offset_left=f"{x * CELL}.0",
                       offset_top=f"{(y - up) * CELL}.0", offset_right=f"{(x + w) * CELL}.0",
                       offset_bottom=f"{(y + h) * CELL}.0", texture=f'ExtResource("{wall_texture}")',
                       expand_mode="1", stretch_mode="6")
        elif picture.exists():
            size = Image.open(picture).size
            scale = w * CELL * 1.08 / size[0]  # A little wider than its footprint, like the village's buildings.
            texture = scene.texture(f"res://assets/maps/{plan['id']}/{item['name']}.png")
            scene.node(item["name"], "Sprite2D", "Map", texture_filter="1",
                       position=f"Vector2({(x + w / 2) * CELL}, {(y + h) * CELL})", scale=f"Vector2({scale:.4f}, {scale:.4f})",
                       texture=f'ExtResource("{texture}")', offset=f"Vector2(0, {-size[1] / 2:.1f})")
        else:
            scene.node(item["name"], "ColorRect", "Map", z_index="-19", offset_left=f"{x * CELL}.0",
                       offset_top=f"{y * CELL}.0", offset_right=f"{(x + w) * CELL}.0",
                       offset_bottom=f"{(y + h) * CELL}.0", color=BLOCKS[kind])
    scene.node("M2Objects", "Node2D", ".", y_sort_enabled="true")
    scene.node("Foliage", "Node2D", ".", y_sort_enabled="true")
    if trees:
        foliage = scene.texture(FOLIAGE)
        oak = scene.atlas(foliage, OAK)
        for item in trees:
            x, y, _, _ = item["cells"]
            painted = folder / f"{item['tree']}.png"
            if painted.exists():
                size = Image.open(painted).size
                texture = scene.texture(f"res://assets/maps/{plan['id']}/{item['tree']}.png")
                scale = 3.2 * CELL / size[0]
                scene.node(item["name"], "Sprite2D", "Foliage", texture_filter="1",
                           position=f"Vector2({(x + 0.5) * CELL}, {(y + 1) * CELL})", scale=f"Vector2({scale:.4f}, {scale:.4f})",
                           texture=f'ExtResource("{texture}")', offset=f"Vector2(0, {-size[1] / 2:.1f})")
            else:
                scene.node(item["name"], "Sprite2D", "Foliage", texture_filter="1",
                           position=f"Vector2({(x + 0.5) * CELL}, {(y + 1) * CELL})", scale="Vector2(0.16, 0.16)",
                           texture=f'SubResource("{oak}")', offset="Vector2(0, -380)")
    return scene.text()


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ids = [a for a in argv if not a.startswith("--")]
    if not ids:
        print(__doc__)
        return 1
    for map_id in ids:
        plan = json.loads((ROOT / "data" / "maps" / f"{map_id}.json").read_text(encoding="utf-8"))
        folder = ROOT / "assets" / "maps" / map_id
        if "--paint" in argv:
            if config.mode() != "live":
                print("Add OPENAI_API_KEY to backend/.env (and don't set AI_MODE=stub) to paint.")
                return 1
            paint(plan, folder, "--force" in argv)
        target = ROOT / "scenes" / "maps" / f"{map_id}.tscn"
        target.write_text(build(plan, folder), encoding="utf-8", newline="\n")
        print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
