# Class Diagram

## System Architecture Overview

```mermaid
classDiagram
    %% Core Protocols
    class StateStore {
        <<protocol>>
        +create(session_id: str | None) ConversationState
        +get(session_id: str) ConversationState
        +save(state: ConversationState) None
        +delete(session_id: str) None
    }

    class OutputHandler {
        <<protocol>>
        +on_llm_response(response: dict) None
        +on_action_start(action_type: str) None
        +on_state_update(state: dict) None
        +display(content: str) None
    }

    class LLMClient {
        <<protocol>>
        +ainvoke(messages: list, response_format: dict) dict
    }

    class Action {
        <<abstract>>
        +type: str
        +payload: dict
        +execute(state: ConversationState)* str | None
    }

    %% State Management
    class ConversationState {
        +session_id: str
        +started_at: datetime
        +last_activity: datetime
        +messages: list[Message]
        +collected_fields: dict[str, FieldData]
        +total_attempts: int
        +escalated: bool
        +escalation_reason: str | None
        +steps: list[StepInfo]
        +add_message(role, content) None
        +collect_field(field, value, confidence) None
        +set_escalation(reason) None
    }

    class FieldData {
        +value: Any
        +confidence: float
        +validation_status: str
        +collected_at: datetime
    }

    class Message {
        +role: str
        +content: str
        +timestamp: datetime
    }

    class StepInfo {
        +step_key: str
        +status: str
    }

    %% State Store Implementations
    class MemoryStateStore {
        -_states: dict[str, ConversationState]
    }

    class FileStateStore {
        -_dir: Path
        +_path(session_id) Path
    }

    %% Action Classes
    class SendMessageAction {
        +type: "send_message"
        +execute(state) str
    }

    class CollectFieldAction {
        +type: "collect_field"
        +execute(state) None
    }

    class UpdateStateAction {
        +type: "update_state"
        +execute(state) None
    }

    class EscalateAction {
        +type: "escalate"
        +execute(state) None
    }

    %% Configuration (Pydantic)
    class Config {
        +agent: AgentConfig
        +personality: PersonalityConfig
        +collection: CollectionConfig
        +fields: list[FieldConfig]
        +actions: ActionsConfig
        +escalation: EscalationConfig
        +system_prompt: SystemPromptConfig
        +load(path: str)$ Config
    }

    %% Runtime Components
    class PromptBuilder {
        -_config: Config
        +build(state: ConversationState) str
    }

    class ActionParser {
        -_registry: dict
        +parse(raw_actions: list[dict]) list[Action]
    }

    class Runtime {
        -_config: Config
        -_store: StateStore
        -_llm: LLMClient
        -_prompt_builder: PromptBuilder
        -_parser: ActionParser
        -_output: OutputHandler
        +start_session(session_id?) str
        +end_session(session_id) None
        +process_message(session_id, user_message) None
        -_meets_confidence(action) bool
    }

    %% LLM Implementation
    class OpenRouterClient {
        -_model: str
        -_temperature: float
        -_max_tokens: int
        -_headers: dict
        +ainvoke(messages, response_format) dict
    }

    %% CLI (implements OutputHandler)
    class CLI {
        -_config: Config
        -_console: Console
        -_fields: list[str]
        -_last_state: dict | None
        -_session_id: str
        -_total_tokens: int
        -_has_tty: bool
        +on_llm_response(response) None
        +on_action_start(action_type) None
        +on_state_update(state) None
        +display(content) None
        +get_user_input() str | None
        +run(runtime) None
        -_get_input() str | None
        -_thinking() AsyncContextManager
        -_render_status_bar() None
        -_setup_terminal() None
        -_teardown_terminal() None
    }

    %% Relationships
    StateStore <|.. MemoryStateStore : implements
    StateStore <|.. FileStateStore : implements
    OutputHandler <|.. CLI : implements
    LLMClient <|.. OpenRouterClient : implements
    Action <|-- SendMessageAction
    Action <|-- CollectFieldAction
    Action <|-- UpdateStateAction
    Action <|-- EscalateAction
    ConversationState *-- FieldData
    ConversationState *-- Message
    ConversationState *-- StepInfo

    Runtime o-- Config
    Runtime o-- StateStore
    Runtime o-- LLMClient
    Runtime o-- PromptBuilder
    Runtime o-- ActionParser
    Runtime o-- OutputHandler

    PromptBuilder o-- Config
    PromptBuilder ..> ConversationState : reads
    ActionParser ..> Action : creates
    Action ..> ConversationState : mutates

    CLI o-- Runtime
```

## Key Design Patterns

### 1. Command Pattern
- `Action` classes encapsulate operations as objects
- Each Action self-executes via `execute(state) -> str | None`
- Runtime iterates actions without knowing their implementation
- Only `SendMessageAction` returns displayable text; others return `None`

### 2. Repository Pattern
- `StateStore` Protocol provides CRUD-only data access
- `MemoryStateStore` — in-memory dict (tests)
- `FileStateStore` — JSON files on disk (production)

### 3. Strategy Pattern
- `LLMClient` Protocol allows swapping implementations (OpenRouter, test mode)
- `OpenRouterClient` uses httpx async with structured JSON output

### 4. Observer Pattern
- `OutputHandler` Protocol decouples Runtime from CLI
- CLI receives real-time callbacks: `on_llm_response`, `on_state_update`, `on_action_start`, `display`
- `on_state_update` called after each action for real-time status bar updates

## Data Flow

1. **User Input** → CLI `_get_input()` → fixed input row (N-1)
2. **CLI** echoes message in scroll area → starts spinner → calls `runtime.process_message()`
3. **Runtime** → saves user message → builds prompt via `PromptBuilder` → calls `LLMClient.ainvoke()`
4. **Runtime** → notifies `on_llm_response()` (tokens update) → `on_state_update()` (pre-action state)
5. **Runtime** → parses actions → for each: `on_action_start()` → `execute(state)` → `on_state_update()` (real-time)
6. **Runtime** → collects display results → `display()` all messages after all actions complete
7. **Runtime** → persists state via `StateStore.save()`

## Terminal Layout (TTY mode)

```
Row 1..(N-3)  — Scroll area: chat messages, action logs, debug panels
Row N-2       — Rule separator (dim line)
Row N-1       — Input prompt: > (or > ⠹ Thinking... during processing)
Row N         — Status bar: session | step | fields | tokens
```
