from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from agent.config.loader import Config
from agent.llm.openrouter import OpenRouterClient
from agent.runtime.runtime import RESPONSE_FORMAT

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)


def _load_config() -> Config:
    return Config.load("configs/example_config.json")


@pytest.mark.asyncio
async def test_openrouter_returns_valid_actions() -> None:
    client = OpenRouterClient(_load_config())
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Return a greeting."},
        {"role": "user", "content": "Hi"},
    ]

    result = await client.ainvoke(messages, RESPONSE_FORMAT)

    assert "actions" in result
    assert isinstance(result["actions"], list)
    assert len(result["actions"]) > 0
    assert result["actions"][0]["type"] in (
        "send_message", "collect_field", "update_state", "escalate",
    )
