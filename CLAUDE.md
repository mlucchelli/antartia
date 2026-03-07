# CLAUDE.md

## Project

Configurable conversational agent (Python 3.11+, async). CLI-based, no HTTP server.

## Architecture

- **Runtime** orchestrates: manages messages, calls PromptBuilder + LLM Client, executes actions, persists state
- **Actions** self-execute on ConversationState, return `str | None` for display
- **LLM Client** is generic: `ainvoke(messages) -> dict`. Knows nothing about agent logic
- **PromptBuilder** interpolates system prompt template with config + state
- **StateStore** Protocol (CRUD only), MemoryStateStore implementation
- **OutputHandler** Protocol for CLI visibility of action execution

## Key Files

- `configs/example_config.json` - agent configuration
- `session_states/example_state.json` - example conversation state
- `docs/PLAN.md` - implementation plan
- `docs/class_diagram.md` - class diagram

## Commands

```bash
pip install -e ".[dev]"          # install with dev deps
pytest                            # run tests
python -m agent --config configs/example_config.json  # run agent
```

## Style

- Use pydantic for models
- Use Protocol over ABC where possible
- Async throughout
- Keep it simple - no over-engineering
