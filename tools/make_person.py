"""Paint a person for a level (GDD D-59): a four-view sheet in the village's style, from their card's look.

    backend/.venv/Scripts/python.exe tools/make_person.py <npc_id> [--tries 3] [--force]
    backend/.venv/Scripts/python.exe tools/make_person.py --measure <sheet.png>

Needs OPENAI_API_KEY in backend/.env. Asks the image model (MODEL_IMAGE) for the sheet with two village sheets as
style references, checks it (four figures, one in each quarter, about the same height, on a clear background), and
writes assets/people/<name>.png and <name>.json beside it: the box of each view, which the rig reads
(scripts/painted_actor.gd, sheet_for). <name> is the person's name in lower case, as the client looks it up.
Then let Godot import it:
    Godot --headless --path . --import
"""

from __future__ import annotations

import base64
import json
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import content  # noqa: E402
from ai import config  # noqa: E402

OUT = ROOT / "assets" / "people"
PROMPT_VERSION = "person_sheet_v1"
PROMPT = (ROOT / "backend" / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
REFERENCES = {"woman": "hessa", "man": "tomas", "child": "jory", "old": "oren"}  # Village sheets to match.
ORDER = [0, 3, 2, 1]  # Front, facing left, back, facing right: which quarter each view is (as the village's).
SOLID = 64  # Alpha this high counts as the figure; fainter specks around it don't.
HAZE = 48  # Fainter than this is haze, cleared away (clean).


def key_of(card: dict) -> str:
    return card["name"].lower().replace(" ", "_")


def views_in(sheet: Image.Image) -> list[list[int]]:
    """The painted box in each quarter (top left, top right, bottom left, bottom right): [x, y, width, height]."""
    alpha = sheet.getchannel("A").point(lambda value: 255 if value >= SOLID else 0)
    half_w, half_h = sheet.width // 2, sheet.height // 2
    boxes = []
    for x0, y0 in ((0, 0), (half_w, 0), (0, half_h), (half_w, half_h)):
        box = alpha.crop((x0, y0, x0 + half_w, y0 + half_h)).getbbox()
        boxes.append([box[0] + x0, box[1] + y0, box[2] - box[0], box[3] - box[1]] if box else [x0, y0, 0, 0])
    return boxes


def clean(sheet: Image.Image) -> Image.Image:
    """Clear the faint haze the model leaves round each figure (it would show as a dark glow on the ground), keeping
    the soft edge of the figure itself."""
    alpha = sheet.getchannel("A").point(lambda a: 0 if a < HAZE else min(255, round((a - HAZE) * 255 / (255 - HAZE))))
    sheet.putalpha(alpha)
    return sheet


def problems(sheet: Image.Image) -> list[str]:
    """What's wrong with a sheet for the rig, if anything."""
    found = []
    half_w, half_h = sheet.width // 2, sheet.height // 2
    boxes = views_in(sheet)
    heights = [box[3] for box in boxes]
    for index, (x, y, w, h) in enumerate(boxes):
        x0, y0 = (index % 2) * half_w, (index // 2) * half_h
        if h < half_h * 0.5:
            found.append(f"view {index}: too small or missing")
        elif x <= x0 + 2 or y <= y0 + 2 or x + w >= x0 + half_w - 2 or y + h >= y0 + half_h - 2:
            found.append(f"view {index}: touches the edge of its quarter")
    if min(heights) < max(heights) * 0.85:
        found.append(f"the views differ in height ({min(heights)} to {max(heights)} px)")
    corners = [sheet.getpixel((x, y))[3] for x in (0, sheet.width - 1) for y in (0, sheet.height - 1)]
    if max(corners) >= SOLID:
        found.append("the background isn't clear")
    return found


def paint(card: dict, kind: str) -> tuple[bytes, dict]:
    prompt = PROMPT.replace("{name}", card["name"]).replace("{role}", card["role"]).replace("{look}", card["look"])
    references = [ROOT / "assets" / "generated" / f"{REFERENCES[k]}_painted_turnaround.png" for k in (kind, "man")]
    with ExitStack() as files:
        images = [files.enter_context(path.open("rb")) for path in dict.fromkeys(references)]
        response = config.client().images.edit(
            model=config.image_model(),
            image=images,
            prompt=prompt,
            size="1024x1536",
            quality="high",
            background="transparent",
            output_format="png",
            n=1,
        )
    usage = getattr(response, "usage", None)
    return base64.b64decode(response.data[0].b64_json), (usage.model_dump() if usage else {})


def make(npc_id: str, tries: int, force: bool) -> int:
    card = content.CARDS.get(npc_id)
    if card is None or not card.get("look"):
        print(f"{npc_id}: no card with a 'look' (how they look, for the painter)")
        return 1
    key = key_of(card)
    target = OUT / f"{key}.png"
    if target.exists() and not force:
        print(f"{target.relative_to(ROOT)} exists (--force to paint again)")
        return 0
    kind = card.get("look_kind", "woman")  # Which village sheet is closest: woman, man, child or old.
    OUT.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, tries + 1):
        started = time.perf_counter()
        data, usage = paint(card, kind)
        draft = OUT / f"{key}.try{attempt}.png"
        draft.write_bytes(data)
        sheet = clean(Image.open(draft).convert("RGBA"))
        sheet.save(draft)
        found = problems(sheet)
        print(f"try {attempt}: {time.perf_counter() - started:.0f} s, usage {usage}, {'; '.join(found) or 'good'}")
        if not found:
            draft.replace(target)
            spec = {"views": views_in(sheet), "order": ORDER, "gait": 1.0, "made_by": config.image_model(),
                    "prompt_version": PROMPT_VERSION}
            (OUT / f"{key}.json").write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
            print(f"wrote {target.relative_to(ROOT)} and {key}.json")
            return 0
    print(f"No good sheet in {tries} tries; the drafts are in {OUT.relative_to(ROOT)} (*.try*.png).")
    return 2


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if argv[:1] == ["--clean"]:  # A sheet painted before the cleaning step.
        clean(Image.open(argv[1]).convert("RGBA")).save(argv[1])
        return 0
    if argv[:1] == ["--measure"]:
        sheet = Image.open(argv[1]).convert("RGBA")
        print(json.dumps({"views": views_in(sheet), "problems": problems(sheet)}))
        return 0
    if config.mode() != "live":
        print("Add OPENAI_API_KEY to backend/.env (and don't set AI_MODE=stub).")
        return 1
    tries = int(argv[argv.index("--tries") + 1]) if "--tries" in argv else 3
    ids = [a for a in argv if a.startswith("npc_")]
    return max((make(npc_id, tries, "--force" in argv) for npc_id in ids), default=1)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
