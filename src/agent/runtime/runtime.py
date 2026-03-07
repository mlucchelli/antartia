from __future__ import annotations

import logging
from typing import Any

from agent.config.loader import Config
from agent.llm.client import LLMClient
from agent.llm.prompt_builder import PromptBuilder
from agent.models.state import StepInfo
from agent.runtime.parser import ActionParser
from agent.runtime.protocols import OutputHandler
from agent.state.store import StateStore

logger = logging.getLogger(__name__)

_SEND_MESSAGE = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["send_message"]},
        "payload": {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
    },
    "required": ["type", "payload"],
    "additionalProperties": False,
}

_COLLECT_FIELD = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["collect_field"]},
        "payload": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "value": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["field", "value", "confidence"],
            "additionalProperties": False,
        },
    },
    "required": ["type", "payload"],
    "additionalProperties": False,
}

_UPDATE_STATE = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["update_state"]},
        "payload": {
            "type": "object",
            "properties": {
                "steps": {
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step_key": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                                "required": ["step_key", "status"],
                                "additionalProperties": False,
                            },
                        },
                        {"type": "null"},
                    ],
                },
                "total_attempts": {
                    "anyOf": [
                        {"type": "integer"},
                        {"type": "null"},
                    ],
                },
            },
            "required": ["steps", "total_attempts"],
            "additionalProperties": False,
        },
    },
    "required": ["type", "payload"],
    "additionalProperties": False,
}

_ESCALATE = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["escalate"]},
        "payload": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
    "required": ["type", "payload"],
    "additionalProperties": False,
}

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "anyOf": [_SEND_MESSAGE, _COLLECT_FIELD, _UPDATE_STATE, _ESCALATE],
                    },
                },
            },
            "required": ["actions"],
            "additionalProperties": False,
        },
    },
}


class Runtime:
    def __init__(
        self,
        config: Config,
        state_store: StateStore,
        llm_client: LLMClient,
        output: OutputHandler,
    ) -> None:
        self._config = config
        self._store = state_store
        self._llm = llm_client
        self._prompt_builder = PromptBuilder(config)
        self._parser = ActionParser(config.collection.confidence_threshold)
        self._output = output

    async def start_session(self, session_id: str | None = None) -> str:
        state = await self._store.create(session_id)

        # Initialize steps from config
        state.steps = [
            StepInfo(step_key=s.key, status=s.initial_status)
            for s in self._config.steps
        ]

        # Add configured greeting to state and notify output
        greeting = self._config.agent.greeting
        state.add_message("assistant", greeting)
        await self._store.save(state)
        self._output.on_state_update(state.model_dump())
        self._output.display(greeting)

        return state.session_id

    async def end_session(self, session_id: str) -> None:
        await self._store.delete(session_id)

    async def process_message(self, session_id: str, user_message: str) -> None:
        state = await self._store.get(session_id)

        # Build system prompt from config + current state
        system_prompt = self._prompt_builder.build(state)

        # Save user message to state
        state.add_message("user", user_message)

        # Build messages array: system + history + current message
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for msg in state.messages:
            messages.append({"role": msg.role, "content": msg.content})

        # Debug: dump system prompt before LLM call
        self._output.on_system_prompt(system_prompt)

        # Call LLM — messages format aligned with OpenRouter API
        response = await self._llm.ainvoke(messages, RESPONSE_FORMAT)

        # Debug: show LLM response and current state before executing
        self._output.on_llm_response(response)
        self._output.on_state_update(state.model_dump())

        # Parse raw actions from response
        raw_actions = self._extract_actions(response)
        actions = self._parser.parse(raw_actions)

        # Execute all actions, collect display results
        display_results: list[str] = []
        for action in actions:
            self._output.on_action_start(action.type)
            result = await action.execute(state)
            self._output.on_state_update(state.model_dump())
            if result is not None:
                display_results.append(result)

        # Display messages after all actions have been logged
        for result in display_results:
            self._output.display(result)

        # Persist updated state
        await self._store.save(state)

    def _extract_actions(self, response: dict) -> list[dict]:
        raw = response.get("actions")
        if raw is None:
            logger.warning("LLM response missing 'actions' key: %s", response)
            return []
        if not isinstance(raw, list):
            logger.warning("LLM 'actions' is not a list: %s", type(raw))
            return []
        return raw
