```json
{
  "project": {
    "name": "conversational-agent",
    "version": "0.1.0",
    "description": "Configurable conversational agent that collects user information, handles small talk, and escalates to a human when appropriate. CLI-based, no HTTP server.",
    "language": "Python",
    "min_python": "3.11",
    "entry_point": "python -m agent --config <config_file>",
    "package_root": "src/agent"
  },

  "dependencies": {
    "runtime": ["pydantic>=2.0", "httpx>=0.25", "python-dotenv>=1.0", "rich>=13.0"],
    "dev": ["pytest>=7.0", "pytest-asyncio>=0.23"],
    "build": ["setuptools>=68.0"]
  },

  "environment": {
    "OPENROUTER_API_KEY": "required — API key for OpenRouter LLM provider"
  },

  "commands": {
    "install": "pip install -e '.[dev]'",
    "test": "pytest -v",
    "run": "python -m agent --config configs/example_config.json",
    "run_debug": "python -m agent --config configs/example_config.json --debug",
    "run_test_mode": "python -m agent --config configs/example_config.json --test",
    "resume_session": "python -m agent --config configs/example_config.json --session <session_id>"
  },

  "architecture": {
    "pattern": "Action-Driven Runtime",
    "summary": "The LLM returns structured JSON with an 'actions' array. The Runtime executes actions sequentially on ConversationState. The agent decides; the runtime executes.",
    "design_patterns": [
      "Command Pattern — Action classes encapsulate operations as objects; each self-executes via execute(state) -> str | None",
      "Repository Pattern — StateStore Protocol with swappable implementations (Memory for tests, File for production)",
      "Strategy Pattern — LLMClient Protocol allows swapping LLM providers",
      "Observer Pattern — OutputHandler Protocol decouples Runtime from CLI; callbacks fire on every action"
    ],
    "key_rules": [
      "Only SendMessageAction returns displayable text; CollectFieldAction, UpdateStateAction, EscalateAction return None",
      "Display messages are buffered until all actions complete to prevent interleaved output",
      "Confidence threshold is enforced both in system prompt (LLM side) and at runtime (defense-in-depth)",
      "send_message MUST always be the last action in every LLM response",
      "EscalateAction only sets escalated=True on state; the goodbye message is sent via a preceding send_message",
      "Steps are managed by the LLM via update_state — runtime only initializes them from config"
    ]
  },

  "file_structure": {
    "src/agent/__main__.py": "Entry point — argparse (--config, --test, --debug, --session), wires Config + Store + LLM + CLI + Runtime",
    "src/agent/config/loader.py": "Pydantic Config model hierarchy + Config.load(path) classmethod",
    "src/agent/cli/app.py": "CLI class — implements OutputHandler, runs async chat loop, TTY terminal layout with scroll region + status bar + spinner",
    "src/agent/llm/client.py": "LLMClient Protocol — ainvoke(messages, response_format) -> dict",
    "src/agent/llm/openrouter.py": "OpenRouterClient — httpx async POST to OpenRouter, parses JSON response, attaches _usage",
    "src/agent/llm/prompt_builder.py": "PromptBuilder — interpolates system_prompt.template with config + state using {placeholder} syntax",
    "src/agent/models/actions.py": "Action ABC + SendMessageAction, CollectFieldAction, UpdateStateAction, EscalateAction",
    "src/agent/models/state.py": "ConversationState, Message, FieldData, StepInfo — all Pydantic BaseModels",
    "src/agent/runtime/parser.py": "ActionParser — maps action type strings to Action classes via ACTION_REGISTRY",
    "src/agent/runtime/protocols.py": "OutputHandler Protocol — on_llm_response, on_system_prompt, on_action_start, on_state_update, display",
    "src/agent/runtime/runtime.py": "Runtime orchestrator — start_session, end_session, process_message + RESPONSE_FORMAT JSON schema",
    "src/agent/state/store.py": "StateStore Protocol + MemoryStateStore (dict-backed, deep-copies state)",
    "src/agent/state/file_store.py": "FileStateStore — JSON file per session in a configurable directory",
    "configs/example_config.json": "Customer service agent config (4 fields: name, email, phone, address)",
    "configs/clinic_appointments_config.json": "Clinic appointment booking config",
    "configs/pizza_place_config.json": "Pizza order config",
    "configs/travel_agency_config.json": "Travel agency config",
    "session_states/": "Directory where FileStateStore persists session JSON files",
    "tests/test_runtime.py": "Async integration tests using FakeLLM + FakeOutput + MemoryStateStore"
  },

  "models": {
    "ConversationState": {
      "session_id": "str",
      "started_at": "datetime (UTC)",
      "last_activity": "datetime (UTC)",
      "messages": "list[Message]",
      "collected_fields": "dict[str, FieldData]",
      "total_attempts": "int = 0",
      "escalated": "bool = False",
      "escalation_reason": "str | None",
      "steps": "list[StepInfo]",
      "methods": ["add_message(role, content)", "collect_field(field, value, confidence)", "set_escalation(reason)"]
    },
    "Message": {
      "role": "str (system | user | assistant)",
      "content": "str",
      "timestamp": "datetime (UTC)"
    },
    "FieldData": {
      "value": "Any",
      "confidence": "float",
      "validation_status": "str = 'valid'",
      "collected_at": "datetime (UTC)"
    },
    "StepInfo": {
      "step_key": "str",
      "status": "str (pending | in_progress | completed)"
    }
  },

  "actions": {
    "SendMessageAction": {
      "type": "send_message",
      "payload": {"content": "str"},
      "returns": "str (the content — displayed to user)",
      "side_effects": "Appends assistant message to state.messages"
    },
    "CollectFieldAction": {
      "type": "collect_field",
      "payload": {"field": "str", "value": "str", "confidence": "float (0–1)"},
      "returns": "None (or rejection string if below confidence threshold)",
      "side_effects": "Writes FieldData to state.collected_fields[field]",
      "note": "confidence_threshold injected by ActionParser from config.collection.confidence_threshold"
    },
    "UpdateStateAction": {
      "type": "update_state",
      "payload": {"steps": "list[{step_key, status}] | null", "total_attempts": "int | null"},
      "returns": "None",
      "side_effects": "Overwrites state.steps and/or state.total_attempts"
    },
    "EscalateAction": {
      "type": "escalate",
      "payload": {"reason": "str"},
      "returns": "None",
      "side_effects": "Sets state.escalated=True, state.escalation_reason=reason"
    }
  },

  "protocols": {
    "StateStore": {
      "create": "async (session_id: str | None) -> ConversationState",
      "get": "async (session_id: str) -> ConversationState",
      "save": "async (state: ConversationState) -> None",
      "delete": "async (session_id: str) -> None",
      "implementations": ["MemoryStateStore (tests)", "FileStateStore (production)"]
    },
    "LLMClient": {
      "ainvoke": "async (messages: list[dict[str,str]], response_format: dict) -> dict",
      "implementations": ["OpenRouterClient", "TestLLM (canned responses for --test mode)"]
    },
    "OutputHandler": {
      "on_llm_response": "(response: dict) -> None",
      "on_system_prompt": "(prompt: str) -> None",
      "on_action_start": "(action_type: str) -> None",
      "on_state_update": "(state: dict) -> None",
      "display": "(content: str) -> None",
      "implementations": ["CLI", "FakeOutput (tests)"]
    }
  },

  "runtime_flow": {
    "start_session": [
      "StateStore.create(session_id?) -> state",
      "Initialize state.steps from config.steps",
      "Append greeting message to state",
      "StateStore.save(state)",
      "OutputHandler.on_state_update(state)",
      "OutputHandler.display(greeting)",
      "Return session_id"
    ],
    "process_message": [
      "StateStore.get(session_id) -> state",
      "PromptBuilder.build(state) -> system_prompt",
      "state.add_message('user', user_message)",
      "Build messages array: [{role:system,...}] + state.messages",
      "OutputHandler.on_system_prompt(system_prompt)",
      "LLMClient.ainvoke(messages, RESPONSE_FORMAT) -> response",
      "OutputHandler.on_llm_response(response)",
      "OutputHandler.on_state_update(state) [pre-action snapshot]",
      "ActionParser.parse(response['actions']) -> actions",
      "For each action: on_action_start(type) -> action.execute(state) -> on_state_update(state)",
      "Collect non-None execute() results into display_results",
      "OutputHandler.display(result) for each display_result",
      "StateStore.save(state)"
    ]
  },

  "llm_response_format": {
    "description": "Strict JSON schema enforced via OpenRouter response_format",
    "schema": {
      "type": "object",
      "properties": {
        "actions": {
          "type": "array",
          "items": "anyOf [send_message | collect_field | update_state | escalate]"
        }
      },
      "required": ["actions"],
      "additionalProperties": false
    }
  },

  "prompt_builder": {
    "placeholders": [
      "{agent.name}", "{agent.greeting}", "{personality.prompt}",
      "{personality.tone}", "{personality.style}", "{personality.formality}", "{personality.emoji_usage}",
      "{fields}  — JSON array of FieldConfig objects",
      "{actions} — JSON array of ActionDefinition objects",
      "{steps}   — current step status list or '(no steps defined yet)'"
    ],
    "appended_automatically": [
      "Current date/time (prepended)",
      "Dynamic sections from config.system_prompt.dynamic_sections (appended)",
      "Current state context block: session_id, collected_fields, total_attempts, escalated (appended)"
    ]
  },

  "config_schema": {
    "agent": {
      "name": "str — agent display name",
      "greeting": "str — opening message sent on session start",
      "model": "str — LLM model ID (e.g. 'openai/gpt-4o-mini')",
      "temperature": "float = 0.7",
      "max_tokens": "int = 500"
    },
    "personality": {
      "tone": "str",
      "style": "str",
      "formality": "str",
      "emoji_usage": "bool = false",
      "prompt": "str — personality description injected into system prompt"
    },
    "collection": {
      "max_attempts": "int = 3",
      "escalate_on_max_attempts": "bool = true",
      "confidence_threshold": "float = 0.7 — minimum confidence for collect_field to be accepted"
    },
    "steps": [{"key": "str", "initial_status": "str = 'pending'"}],
    "fields": [{
      "name": "str — field key",
      "type": "str (text | email | phone | ...)",
      "req": "bool = true",
      "desc": "str — description injected into system prompt",
      "regex": "str | null — optional validation pattern",
      "abbr": "str | null — short display name for status bar"
    }],
    "actions": {
      "available": [{"type": "str", "description": "str", "parameters": "dict[str,str]"}]
    },
    "escalation": {
      "enabled": "bool",
      "policies": [{"enabled": "bool", "reason": "str", "description": "str"}]
    },
    "system_prompt": {
      "template": "str — markdown template with {placeholder} tokens",
      "dynamic_sections": "dict[str, str] — key/value sections appended to template"
    }
  },

  "cli": {
    "terminal_layout": {
      "rows_1_to_N-3": "Scroll area — chat messages, action logs, debug panels",
      "row_N-2": "Rule separator (dim line)",
      "row_N-1": "Input prompt: ❯  (or ❯ ⠹ Thinking... during processing)",
      "row_N": "Status bar: session | step | field1 ✓ | field2 … | tokens: 1,234"
    },
    "implementation_notes": [
      "ANSI escape codes for scroll region: \\033[1;{N-3}r",
      "Status bar uses cursor save/restore: \\033[s ... \\033[u",
      "Spinner runs as asyncio.create_task during LLM calls (braille frames)",
      "Graceful fallback when not in a TTY (tests, piped input)",
      "Rich library used for console output, panels, markup"
    ],
    "debug_mode": "Shows system prompt panel (magenta), LLM response panel (yellow), state summary panel (cyan)"
  },

  "testing": {
    "framework": "pytest with pytest-asyncio (asyncio_mode=auto)",
    "test_doubles": {
      "FakeLLM": "Queue of preconfigured responses; records (messages, response_format) calls",
      "FakeOutput": "Records action_starts and displayed messages"
    },
    "state_store_for_tests": "MemoryStateStore",
    "test_file": "tests/test_runtime.py",
    "test_count": "~10 runtime integration tests covering: session lifecycle, message processing, each action type, confidence rejection, state persistence"
  },

  "available_configs": [
    "configs/example_config.json — Customer service (name, email, phone, address)",
    "configs/clinic_appointments_config.json — Clinic appointment booking",
    "configs/pizza_place_config.json — Pizza order intake",
    "configs/travel_agency_config.json — Travel agency intake"
  ],

  "session_persistence": {
    "production": "FileStateStore — one JSON file per session in session_states/ directory",
    "file_format": "ConversationState.model_dump_json(indent=2)",
    "resume": "python -m agent --config <cfg> --session <session_id>"
  }
}
```
