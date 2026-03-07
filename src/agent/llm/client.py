from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    async def ainvoke(
        self, messages: list[dict[str, str]], response_format: dict[str, Any]
    ) -> dict: ...
