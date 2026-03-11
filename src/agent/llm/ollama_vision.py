from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from agent.config.loader import Config

logger = logging.getLogger(__name__)

_VISION_PROMPT_SUFFIX = (
    "\n\nRespond with exactly this JSON — no other text:\n"
    '{"description": "<detailed field observation, min 5-7 sentences>", '
    '"summary": "<one sentence, max 15 words>", '
    '"significance_score": <float 0.0-1.0>, '
    '"agent_quote": <string or null>, '
    '"tags": <array of strings>}'
)


@dataclass
class VisionResult:
    description: str        # full detailed field observation
    summary: str            # one-liner for CLI display
    usage: dict             # {"prompt_tokens": int, "completion_tokens": int}
    significance_score: float = 0.5
    agent_quote: str | None = None
    tags: list[str] = field(default_factory=list)


class OllamaVisionClient:
    """
    Sends a JPEG preview to qwen2.5vl via Ollama /api/generate.
    Returns a VisionResult with description, summary, significance score,
    agent quote, and tags — all in a single model call.
    """

    def __init__(self, config: Config) -> None:
        self._model = config.agent.vision_model
        self._base_url = config.photo_pipeline.ollama_url
        self._prompt = (
            config.photo_pipeline.vision_prompt
            + "\n\n"
            + config.photo_pipeline.scoring_prompt
            + _VISION_PROMPT_SUFFIX
        )

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
            "think": False,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/api/generate",
                json=body,
                timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
            )
            resp.raise_for_status()

        resp_json = resp.json()
        raw = resp_json.get("response", "").strip()
        usage = {
            "prompt_tokens": resp_json.get("prompt_eval_count", 0),
            "completion_tokens": resp_json.get("eval_count", 0),
        }

        try:
            parsed = json.loads(raw)
            description = parsed.get("description", raw)
            summary = parsed.get("summary", description[:100])
            score = max(0.0, min(1.0, float(parsed.get("significance_score", 0.5))))
            quote = parsed.get("agent_quote") or None
            if isinstance(quote, str):
                quote = quote.strip() or None
            raw_tags = parsed.get("tags") or []
            tags = [t for t in raw_tags if isinstance(t, str)]
        except (json.JSONDecodeError, ValueError, TypeError):
            description = raw
            summary = raw[:100]
            score = 0.5
            quote = None
            tags = []

        logger.info("Vision: %s — score=%.2f — %s", path.name, score, summary)
        return VisionResult(
            description=description,
            summary=summary,
            usage=usage,
            significance_score=score,
            agent_quote=quote,
            tags=tags,
        )
