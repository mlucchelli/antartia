from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    name: str
    greeting: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 500


class PersonalityConfig(BaseModel):
    tone: str
    style: str
    formality: str
    emoji_usage: bool = False
    prompt: str


class StepConfig(BaseModel):
    key: str
    initial_status: str = "pending"


class CollectionConfig(BaseModel):
    max_attempts: int = 3
    escalate_on_max_attempts: bool = True
    confidence_threshold: float = 0.7


class FieldConfig(BaseModel):
    name: str
    type: str
    req: bool = True
    desc: str
    regex: str | None = None
    abbr: str | None = None

    @property
    def display_name(self) -> str:
        return self.abbr or self.name


class ActionDefinition(BaseModel):
    type: str
    description: str
    parameters: dict[str, str] = Field(default_factory=dict)


class ActionsConfig(BaseModel):
    available: list[ActionDefinition] = Field(default_factory=list)


class EscalationPolicyConfig(BaseModel):
    enabled: bool = True
    reason: str
    description: str


class EscalationConfig(BaseModel):
    enabled: bool = True
    policies: list[EscalationPolicyConfig] = Field(default_factory=list)


class SystemPromptConfig(BaseModel):
    template: str
    dynamic_sections: dict[str, str] = Field(default_factory=dict)


class Config(BaseModel):
    agent: AgentConfig
    personality: PersonalityConfig
    collection: CollectionConfig
    steps: list[StepConfig] = Field(default_factory=list)
    fields: list[FieldConfig]
    actions: ActionsConfig
    escalation: EscalationConfig
    system_prompt: SystemPromptConfig

    @classmethod
    def load(cls, path: str | Path) -> Config:
        path = Path(path)
        with path.open() as f:
            data = json.load(f)
        return cls.model_validate(data)
