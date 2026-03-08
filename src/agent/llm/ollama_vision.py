from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from agent.config.loader import Config

logger = logging.getLogger(__name__)

_VISION_PROMPT_SUFFIX = (
    "\n\nRespond with a JSON object with exactly two fields:\n"
    '{"description": "<detailed multi-sentence analysis>", '
    '"summary": "<one sentence, max 15 words>"}'
)


@dataclass
class VisionResult:
    description: str  # full detailed analysis
    summary: str      # one-liner for CLI display


class OllamaVisionClient:
    """
    Sends a JPEG preview to qwen2.5vl via Ollama /api/generate.
    Returns a VisionResult with a detailed description and a one-line summary.
    """

    def __init__(self, config: Config) -> None:
        self._model = config.agent.vision_model
        self._base_url = config.photo_pipeline.ollama_url
        self._prompt = config.photo_pipeline.vision_prompt + _VISION_PROMPT_SUFFIX

    async def describe(self, image_path: str | Path) -> VisionResult:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        image_b64 = base64.b64encode(path.read_bytes()).decode()

        body = {
            "model": self._model,
            "prompt": self._prompt,
            "images": [image_b64],
            "stream": False,
            "format": "json",
            "keep_alive": -1,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/api/generate",
                json=body,
                timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
            )
            resp.raise_for_status()

        raw = resp.json().get("response", "").strip()

        try:
            parsed = json.loads(raw)
            description = parsed.get("description", raw)
            summary = parsed.get("summary", description[:100])
        except json.JSONDecodeError:
            description = raw
            summary = raw[:100]

        logger.info("Vision: %s — %s", path.name, summary)
        return VisionResult(description=description, summary=summary)
