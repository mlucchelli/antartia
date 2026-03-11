from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from agent.config.loader import Config

logger = logging.getLogger(__name__)

_FORMAT_EXAMPLE = """\
You MUST respond with a JSON object that strictly follows this schema:
{"actions": [{"type": "<action_type>", "payload": {...}}]}

Every response must contain exactly one or more actions. The last action MUST be "send_message".

Example:
{"actions": [{"type": "send_message", "payload": {"content": "Hello."}}]}"""


class OllamaClient:
    def __init__(self, config: Config) -> None:
        self._model = config.agent.model
        self._temperature = config.agent.temperature
        self._base_url = config.photo_pipeline.ollama_url

    async def ainvoke(
        self, messages: list[dict[str, str]], response_format: dict[str, Any]
    ) -> dict:
        # Extract the JSON schema from RESPONSE_FORMAT and pass it to Ollama
        # for native structured output enforcement.
        schema = response_format.get("json_schema", {}).get("schema", None)

        # Inject the format reminder into the last user message so the model
        # sees a concrete example immediately before generating.
        augmented = list(messages)
        if augmented and augmented[-1]["role"] == "user":
            augmented[-1] = {
                "role": "user",
                "content": augmented[-1]["content"] + "\n\n" + _FORMAT_EXAMPLE,
            }

        body: dict[str, Any] = {
            "model": self._model,
            "messages": augmented,
            "stream": False,
            "format": schema if schema else "json",
            "options": {"temperature": self._temperature},
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json=body,
                timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
            )
            resp.raise_for_status()

        data = resp.json()
        content = data["message"]["content"]

        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Ollama returned invalid JSON: %s", exc)
            result = {
                "actions": [
                    {
                        "type": "send_message",
                        "payload": {"content": "Sorry, I had trouble processing that. Could you repeat?"},
                    }
                ]
            }

        result["_usage"] = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }
        return result
