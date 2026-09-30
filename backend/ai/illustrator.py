"""Illustrator role: paints a sprite for a validated object record.

The prompt is built from the committed record (name, description, materials),
never from the player's raw words.
"""

from __future__ import annotations

import base64
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

PROMPT_VERSION = "illustrator_v1"
# The world sprite, the view held in a hand, and the four-view sheet worn on the body (D-49).
VERSIONS = {"world": PROMPT_VERSION, "held": "illustrator_v2_held", "worn": "illustrator_v2_worn"}
_TEMPLATES = {
    view: (Path(__file__).resolve().parents[1] / "prompts" / f"{version}.txt").read_text(encoding="utf-8")
    for view, version in VERSIONS.items()
}
_TEMPLATE = _TEMPLATES["world"]


@dataclass
class SpriteCall:
    status: str  # "ready" | "disabled" | "failed"
    model: str | None = None
    prompt: str = ""
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def sprite_prompt(record: dict) -> str:
    subject = f"a {record['name']}. {record.get('description', '')}".strip()
    materials = ", ".join(record.get("materials") or ["ordinary materials"])
    template = _TEMPLATES.get(record.get("view", "world"), _TEMPLATE)
    return template.replace("{subject}", subject).replace("{materials}", materials)


def generate_sprite(record: dict, destination: Path) -> SpriteCall:
    prompt = sprite_prompt(record)
    version = VERSIONS.get(record.get("view", "world"), PROMPT_VERSION)
    if not config.images_enabled():
        return SpriteCall(
            status="disabled",
            prompt=prompt,
            prompt_version=version,
            error="Image generation is off or no API key is set.",
        )
    if config.mode() == "stub":  # Exercise storage and delivery without a model.
        destination.parent.mkdir(parents=True, exist_ok=True)
        stand_in = Path(__file__).resolve().parents[2] / "assets" / "generated" / "prop_stone.png"
        destination.write_bytes(stand_in.read_bytes())
        return SpriteCall(status="ready", model="stub", prompt=prompt, prompt_version=version)
    started = time.perf_counter()
    call = SpriteCall(status="failed", prompt=prompt, prompt_version=version)
    errors = []
    for model in dict.fromkeys([config.image_model(), config.image_fallback_model()]):
        call.model = model
        try:
            response = config.client().images.generate(
                model=model,
                prompt=prompt,
                size="1024x1024",
                quality=config.image_quality(),
                background="transparent",
                output_format="png",
                n=1,
            )
        except Exception as error:
            errors.append(f"{model}: {type(error).__name__}: {error}")
            if not _model_unavailable(error):
                break
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(base64.b64decode(response.data[0].b64_json))
        call.status, errors = "ready", []
        break
    call.error = " | ".join(errors) or None
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    return call


def _model_unavailable(error: Exception) -> bool:
    from openai import BadRequestError, NotFoundError, PermissionDeniedError

    return isinstance(error, (NotFoundError, PermissionDeniedError)) or (
        isinstance(error, BadRequestError) and "model" in str(error).lower()
    )
