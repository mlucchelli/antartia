from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from agent.config.loader import Config

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, config: Config) -> None:
        load_dotenv()
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not set in environment")

        self._model = config.agent.model
        self._temperature = config.agent.temperature
        self._max_tokens = config.agent.max_tokens
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def ainvoke(
        self, messages: list[dict[str, str]], response_format: dict[str, Any]
    ) -> dict:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_completion_tokens": self._max_tokens,
            "response_format": response_format,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers=self._headers,
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()

        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]

        finish_reason = choice.get("finish_reason", "")
        if finish_reason == "length":
            logger.warning("LLM response truncated (max_tokens reached)")

        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("LLM returned invalid JSON: %s", exc)
            result = {
                "actions": [
                    {
                        "type": "send_message",
                        "payload": {
                            "content": "Sorry, I had trouble processing that. Could you repeat?"
                        },
                    }
                ]
            }

        result["_usage"] = data.get("usage", {})
        return result
