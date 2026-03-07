# Conversational Agent
<img width="1238" height="399" alt="image" src="https://github.com/user-attachments/assets/2e0c5a32-fab4-49f7-848d-e88a1547eccf" />
A configurable, action-driven conversational agent (Python 3.11+, async) that collects user information through natural conversation. All behavior is defined in a single JSON configuration file: fields to collect, personality, system prompt, escalation policies. No code changes needed to create a new agent.

## Prerequisites

- **Python 3.11+** — check with `python3 --version`
- **pip** — comes with Python, check with `pip --version`
- **git** — to clone the repository

If you don't have Python 3.11+, install it via your package manager:

```bash
# macOS (Homebrew)
brew install python@3.11

# Ubuntu/Debian
sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip

# Arch
sudo pacman -S python

# Windows
# Download from https://www.python.org/downloads/
```

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd konko_challenge

# 2. Create and activate virtualenv
python3 -m venv .venv
source .venv/bin/activate       # bash/zsh
source .venv/bin/activate.fish  # fish
# Windows: .venv\Scripts\activate

# 3. Install the package and all dependencies
pip install -e ".[dev]"
# Or alternatively, using requirements files:
#   pip install -r requirements-dev.txt

# 4. Set your OpenRouter API key
cp .env.example .env
# Edit .env with your key:
#   OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx

# 5. Run the agent
python -m agent --config configs/example_config.json
```

## CLI Options

```bash
python -m agent --config <path>              # required: path to config JSON
python -m agent --config <path> --debug      # show raw LLM responses and state
python -m agent --config <path> --test       # test mode (no API calls, canned responses)
python -m agent --config <path> --session <id>   # resume an existing session
```

| Flag | Description |
|------|-------------|
| `--config` | Path to the agent configuration JSON (required) |
| `--debug` | Show raw LLM response and final state each turn |
| `--test` | Use a fake LLM that echoes input (no API key needed) |
| `--session` | Resume a previous session by its ID |

## Environment

The only environment variable needed is your OpenRouter API key:

```bash
# .env
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx
```

Get a key at [openrouter.ai](https://openrouter.ai/). The agent uses the model specified in your config (e.g., `openai/gpt-4o-mini`).

## Configuration

Everything is driven by a single JSON file. Four example configs are included:

| Config | Agent |
|--------|-------|
| [`configs/example_config.json`](configs/example_config.json) | Customer Service Agent |
| [`configs/pizza_place_config.json`](configs/pizza_place_config.json) | Pizza Order Assistant |
| [`configs/clinic_appointments_config.json`](configs/clinic_appointments_config.json) | CliniK |
| [`configs/travel_agency_config.json`](configs/travel_agency_config.json) | Travel Booking Assistant |

To create a new agent, copy any config and modify the fields, personality, and system prompt template. The CLI, runtime, and LLM integration adapt automatically.

## Sessions

Sessions are persisted as JSON files in the `session_states/` directory. Each session gets a unique UUID as its filename.

### Resume a session

```bash
# List available sessions
ls session_states/

# Resume by ID (filename without .json)
python -m agent --config configs/example_config.json --session 330ebf6308114dde8f076ca6efda9697
```

When resuming, the agent shows the last assistant message for context and continues the conversation from where it left off.

### Session file format

Session files contain the full `ConversationState` serialized as JSON: message history, collected fields, steps, escalation status. They are human-readable and can be inspected directly:

```bash
cat session_states/330ebf6308114dde8f076ca6efda9697.json | python -m json.tool
```

## Terminal UI

The CLI uses [Rich](https://rich.readthedocs.io/) with a fixed terminal layout:

```
Customer Service Agent: Hello! I'm here to help...     <- scroll area (chat history)
> mario lucchelli                                       <- scroll area (echoed input)
  executing: collect_field                              <- scroll area (action logs)
  executing: send_message
Customer Service Agent: Thanks! What's your email?
──────────────────────────────────────────────────────  <- fixed: rule separator
> ⠹ Thinking...                                        <- fixed: input row (with spinner)
session: 7ddec... │ step: collecting │ name ✓ │ email … <- fixed: status bar
```

- **Scroll area** (rows 1..N-3): chat messages, action logs, debug panels
- **Rule separator** (row N-2): dim line separating chat from input
- **Input row** (row N-1): `>` prompt, shows animated spinner while waiting for LLM
- **Status bar** (row N): session ID, current step, field progress with checkmarks, token count

The status bar updates in real-time as fields are collected.

## Project Structure

```
src/agent/
├── __main__.py              Entry point (CLI args, wiring)
├── config/
│   └── loader.py            Pydantic config models + Config.load()
├── cli/
│   └── app.py               Terminal UI (Rich, scroll region, spinner, status bar)
├── llm/
│   ├── client.py            LLMClient Protocol
│   ├── openrouter.py        OpenRouter implementation (httpx async)
│   └── prompt_builder.py    System prompt template interpolation
├── models/
│   ├── actions.py           Action classes (SendMessage, CollectField, UpdateState, Escalate)
│   └── state.py             ConversationState, Message, FieldData, StepInfo
├── runtime/
│   ├── parser.py            ActionParser (dict → Action instances)
│   ├── protocols.py         OutputHandler Protocol
│   └── runtime.py           Runtime orchestrator + JSON schema for structured output
└── state/
    ├── file_store.py        FileStateStore (JSON files per session)
    └── store.py             StateStore Protocol + MemoryStateStore

configs/                     Agent configuration files
session_states/              Persisted session JSON files
docs/                        Architecture docs (PLAN.md, class_diagram.md)
tests/                       Test suite (53 tests)
pyproject.toml               Package config, dependencies, build system
requirements.txt             Runtime dependencies (flat)
requirements-dev.txt         Runtime + dev dependencies (flat)
.env.example                 Template for environment variables
```

## Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_runtime.py -v

# Run the OpenRouter integration test (requires API key)
pytest tests/test_openrouter.py -v
```

**53 tests** covering:

| Test File | Tests | What it covers |
|-----------|-------|----------------|
| `test_runtime.py` | 11 | Session lifecycle, message processing, action execution |
| `test_state_store.py` | 9 | MemoryStateStore CRUD operations |
| `test_file_store.py` | 8 | FileStateStore persistence (uses tmp_path) |
| `test_cli.py` | 8 | CLI behavior, greeting, multi-turn, exit handling |
| `test_prompt_builder.py` | 9 | Template interpolation, state context, dynamic sections |
| `test_parser.py` | 7 | Action parsing, validation, unknown types |
| `test_openrouter.py` | 1 | Integration test (skipped without API key) |

## Dependencies

All dependencies are declared in [`pyproject.toml`](pyproject.toml) and installed automatically by `pip install -e ".[dev]"`. Flat requirements files are also available: [`requirements.txt`](requirements.txt) (runtime) and [`requirements-dev.txt`](requirements-dev.txt) (includes test deps).

**Runtime:**

| Package | Version | Purpose |
|---------|---------|---------|
| pydantic | >= 2.0 | Config and state models |
| httpx | >= 0.25 | Async HTTP client for OpenRouter API |
| python-dotenv | >= 1.0 | `.env` file loading |
| rich | >= 13.0 | Terminal UI (panels, rules, styled text) |

**Dev only** (installed with `.[dev]`):

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | >= 7.0 | Test framework |
| pytest-asyncio | >= 0.23 | Async test support |

## Session Debugger

A self-contained HTML viewer for inspecting session state files. Open it directly in your browser — no server required.

```bash
open tools/session_debugger.html       # macOS
xdg-open tools/session_debugger.html   # Linux
```

Sessions from `session_states/` are embedded in the file. You can also load additional JSON files via the **+ Load files** button in the sidebar.

The debugger provides:
- **Sidebar** with session list, search/filter, status indicators
- **Preview tab** with step pipeline and full message history
- **Fields tab** with collected values, confidence scores, and validation status
- **Formatted JSON tab** with syntax highlighting and copy button

## Documentation

- [Architecture Plan](docs/PLAN.md) — design decisions, data flow, commit history
- [Class Diagram](docs/class_diagram.md) — mermaid class diagram with all protocols and implementations
- [Session Debugger](tools/session_debugger.html) — visual session inspector
