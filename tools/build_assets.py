"""Turn the three generated source images into fixed-size M0 game assets."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "source" / "generated"
OUT = ROOT / "assets" / "generated"
OUT.mkdir(parents=True, exist_ok=True)


def character(name: str) -> None:
    image = Image.open(SOURCE / f"{name}_source.png").convert("RGBA")
    alpha = image.getchannel("A")
    # Image generation can leave nearly transparent pixels across the canvas.
    box = alpha.point(lambda value: 255 if value >= 32 else 0).getbbox()
    if box is None:
        raise ValueError(f"{name} source has no visible pixels")
    cutout = image.crop(box)
    cutout.thumbnail((39, 44), Image.Resampling.LANCZOS)
    frame = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    frame.alpha_composite(cutout, ((48 - cutout.width) // 2, 47 - cutout.height))
    frame.save(OUT / f"{name}_idle.png")


for actor in ("traveler", "guard"):
    character(actor)

gate = Image.open(SOURCE / "city_gate_source.png").convert("RGBA")
gate_box = gate.getchannel("A").point(lambda value: 255 if value >= 32 else 0).getbbox()
if gate_box is None:
    raise ValueError("City gate source has no visible pixels")
gate = gate.crop(gate_box)
gate.thumbnail((160, 160), Image.Resampling.LANCZOS)
gate_frame = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
gate_frame.alpha_composite(gate, ((160 - gate.width) // 2, 160 - gate.height))
gate_frame.save(OUT / "city_gate_closed.png")

wall = Image.open(SOURCE / "city_wall_source.png").convert("RGB")
wall_width, wall_height = wall.size
wall.crop((wall_width * 2 // 5, 0, wall_width * 3 // 5, wall_height)).resize(
    (64, 160), Image.Resampling.LANCZOS
).save(OUT / "city_wall_segment.png")

terrain = Image.open(SOURCE / "earth_source.png").convert("RGB")
# A large, unique source crop avoids repetition within the compact greybox.
world = terrain.resize((3072, 2304), Image.Resampling.LANCZOS)
world.save(OUT / "earth_world.jpg", quality=88, optimize=True)
print("Created traveler/guard sprites, gate, wall segment, and terrain")
