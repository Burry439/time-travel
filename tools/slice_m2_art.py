"""Crop the two generated M2 prop atlases into transparent game textures."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "source" / "generated"
OUTPUT = ROOT / "assets" / "generated"

for atlas, crops in {
    "m2_road_atlas.png": [
        ("prop_branch.png", (0, 0, 627, 627)),
        ("prop_cord.png", (627, 0, 1254, 627)),
        ("prop_bucket.png", (0, 627, 627, 1254)),
        ("prop_trough.png", (627, 627, 1254, 1254)),
    ],
    "m2_material_atlas.png": [
        ("prop_stone.png", (0, 0, 896, 896)),
        ("prop_plank.png", (896, 0, 1792, 896)),
    ],
}.items():
    image = Image.open(SOURCE / atlas).convert("RGBA")
    for name, box in crops:
        part = image.crop(box)
        bounds = part.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError(f"Empty alpha in {name}")
        part = part.crop(bounds)
        part.thumbnail((128, 128), Image.Resampling.LANCZOS)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        part.save(OUTPUT / name)
        print(name, part.size)
