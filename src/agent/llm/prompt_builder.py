from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.config.loader import Config
from agent.models.state import ConversationState


class PromptBuilder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def build(self, state: ConversationState) -> str:
        template = self._config.system_prompt.template

        # Replace dot-notation placeholders from config
        replacements = {
            "{agent.name}": self._config.agent.name,
            "{agent.greeting}": self._config.agent.greeting,
            "{personality.prompt}": self._config.personality.prompt,
            "{personality.tone}": self._config.personality.tone,
            "{personality.style}": self._config.personality.style,
            "{personality.formality}": self._config.personality.formality,
            "{personality.emoji_usage}": str(self._config.personality.emoji_usage),
        }
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)

        # Replace {fields} with JSON field configs
        fields_data = [f.model_dump() for f in self._config.fields]
        template = template.replace("{fields}", json.dumps(fields_data, indent=2))

        # Replace {actions} with JSON action definitions
        actions_data = [a.model_dump() for a in self._config.actions.available]
        template = template.replace("{actions}", json.dumps(actions_data, indent=2))

        # Replace {steps} with current step state
        template = template.replace("{steps}", self._build_steps(state))

        # Append dynamic sections from config
        dynamic = self._config.system_prompt.dynamic_sections
        if dynamic:
            sections = "\n".join(dynamic.values())
            template = f"{template}\n\n{sections}"

        # Inject current date/time
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        template = f"Current date and time: {now}\n\n{template}"

        # Append current state context
        state_context = self._build_state_context(state)
        return f"{template}\n\n{state_context}"

    def _build_steps(self, state: ConversationState) -> str:
        if not state.steps:
            return "(no steps defined yet — use update_state to initialize steps)"
        lines = []
        for s in state.steps:
            lines.append(f"- {s.step_key}: {s.status}")
        return "\n".join(lines)

    def _build_state_context(self, state: ConversationState) -> str:
        collected = {
            k: {"value": v.value, "confidence": v.confidence}
            for k, v in state.collected_fields.items()
        }
        return (
            f"Current state:\n"
            f"- Session: {state.session_id}\n"
            f"- Collected fields: {json.dumps(collected)}\n"
            f"- Total attempts: {state.total_attempts}\n"
            f"- Escalated: {state.escalated}"
        )
