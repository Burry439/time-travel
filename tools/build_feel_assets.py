"""Convert generated source art into reproducible game-ready feel-pass assets."""
from pathlib import Path
import random
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "source" / "generated"
OUT = ROOT / "assets" / "generated"
OUT.mkdir(parents=True, exist_ok=True)


def clean_alpha(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    alpha = image.getchannel("A").point(lambda value: 0 if value < 24 else value)
    image.putalpha(alpha)
    return image


def walk_sheet(name: str) -> None:
    image = clean_alpha(Image.open(SOURCE / f"{name}_walk_source.png"))
    cell_w, cell_h = image.width // 3, image.height // 4
    output = Image.new("RGBA", (3 * 48, 4 * 64))
    for row in range(4):
        for col in range(3):
            cell = image.crop((col * cell_w, row * cell_h,
                               (col + 1) * cell_w, (row + 1) * cell_h))
            bounds = cell.getchannel("A").getbbox()
            if bounds is None:
                raise ValueError(f"Missing frame {name} ({row}, {col})")
            cutout = cell.crop(bounds)
            cutout.thumbnail((46, 62), Image.Resampling.LANCZOS)
            output.alpha_composite(cutout, (col * 48 + (48 - cutout.width) // 2,
                                            row * 64 + 63 - cutout.height))
    output.save(OUT / f"{name}_walk.png")


def prop(name: str, size: tuple[int, int]) -> None:
    image = clean_alpha(Image.open(SOURCE / f"{name}_source.png"))
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError(f"Empty prop: {name}")
    cutout = image.crop(bounds)
    cutout.thumbnail(size, Image.Resampling.LANCZOS)
    frame = Image.new("RGBA", size)
    frame.alpha_composite(cutout, ((size[0] - cutout.width) // 2,
                                   size[1] - cutout.height))
    frame.save(OUT / f"{name}.png")


for actor in ("traveler", "guard"):
    walk_sheet(actor)
for name, size in {"smithy": (360, 252), "inn": (360, 252),
                   "carpenter": (360, 252), "wagon": (260, 170)}.items():
    prop(name, size)

for atlas, names in (
    ("npc_atlas_a_source.png", ("roderic", "bren", "oren", "hessa")),
    ("npc_atlas_b_source.png", ("mara", "jory", "tomas", "darin")),
):
    source = clean_alpha(Image.open(SOURCE / atlas))
    half_w, half_h = source.width // 2, source.height // 2
    for index, name in enumerate(names):
        col, row = index % 2, index // 2
        quadrant = source.crop((col * half_w, row * half_h,
                                (col + 1) * half_w, (row + 1) * half_h))
        bounds = quadrant.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError(f"Missing NPC sprite: {name}")
        cutout = quadrant.crop(bounds)
        cutout.thumbnail((62, 86), Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", (64, 88))
        frame.alpha_composite(cutout, ((64 - cutout.width) // 2,
                                       87 - cutout.height))
        frame.save(OUT / f"npc_{name}.png")

# Keep roads part of the terrain texture so their edges have the same grain.
world_size = (3072, 2304)


def terrain_layer(source_name: str) -> Image.Image:
    source = Image.open(SOURCE / source_name).convert("RGB")
    world = source.resize(world_size, Image.Resampling.LANCZOS)
    edge = Image.new("L", (768, 768), 0)
    ImageDraw.Draw(edge).rectangle((48, 48, 720, 720), fill=255)
    edge = edge.filter(ImageFilter.GaussianBlur(28))
    rng = random.Random(source_name)
    for y in range(-24, world_size[1], 672):
        for x in range(-24, world_size[0], 672):
            crop_x = rng.randrange(source.width - 768 + 1)
            crop_y = rng.randrange(source.height - 768 + 1)
            patch = source.crop((crop_x, crop_y, crop_x + 768, crop_y + 768))
            world.paste(patch, (x, y), edge)
    return world


grass = terrain_layer("grass_source.png")
earth = terrain_layer("earth_source.png")
mask = Image.new("L", world_size)
draw = ImageDraw.Draw(mask)
draw.line([(1536, 2304), (1536, 1350), (1536, 285)], fill=224, width=190)
draw.line([(950, 1540), (2090, 1540)], fill=210, width=112)
draw.line([(1450, 940), (570, 940)], fill=190, width=85)
draw.line([(1600, 940), (2040, 940), (2570, 1070)], fill=190, width=85)
draw.ellipse((1320, 1990, 1750, 2430), fill=150)
mask = mask.filter(ImageFilter.GaussianBlur(14))
Image.composite(earth, grass, mask).save(OUT / "world_ground.jpg", quality=88,
                                       optimize=True)
print("Built directional sprites, eight unique NPCs, four props, and world ground")
