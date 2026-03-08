from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    name: str
    greeting: str
    model: str
    provider: str = "ollama"  # "ollama" | "openrouter"
    vision_model: str = "qwen2.5vl:7b"
    temperature: float = 0.7
    max_tokens: int = 500


class PersonalityConfig(BaseModel):
    tone: str
    style: str
    formality: str
    emoji_usage: bool = False
    prompt: str


class ActionDefinition(BaseModel):
    type: str
    description: str
    parameters: dict[str, str] = Field(default_factory=dict)


class ActionsConfig(BaseModel):
    available: list[ActionDefinition] = Field(default_factory=list)


class SystemPromptConfig(BaseModel):
    template: str
    dynamic_sections: dict[str, str] = Field(default_factory=dict)


class RuntimeConfig(BaseModel):
    max_chain_depth: int = 6


class HttpServerConfig(BaseModel):
    host: str = Field(default_factory=lambda: os.environ["HTTP_HOST"])
    port: int = Field(default_factory=lambda: int(os.environ["HTTP_PORT"]))


class SchedulerConfig(BaseModel):
    tick_interval_seconds: int = Field(default_factory=lambda: int(os.environ["SCHEDULER_TICK_SECONDS"]))


class DbConfig(BaseModel):
    path: str = Field(default_factory=lambda: os.environ["DB_PATH"])


class PhotoPipelineConfig(BaseModel):
    inbox_dir: str = Field(default_factory=lambda: os.environ["PHOTO_INBOX_DIR"])
    processed_dir: str = Field(default_factory=lambda: os.environ["PHOTO_PROCESSED_DIR"])
    vision_preview_dir: str = Field(default_factory=lambda: os.environ["PHOTO_PREVIEW_DIR"])
    ollama_url: str = Field(default_factory=lambda: os.environ["OLLAMA_URL"])
    significance_threshold: float = 0.75
    vision_prompt: str = "This photo was taken during an Antarctic expedition. Describe in detail what you see: landscape, terrain, people, equipment, weather conditions, lighting, and anything noteworthy. Be specific and objective."
    scoring_prompt: str = "Rate the significance of this Antarctic expedition photo from 0.0 to 1.0. Respond with: {\"significance_score\": <float>}\n\nDescription:\n"


class ImagePreprocessingConfig(BaseModel):
    correct_exif_orientation: bool = True
    vision_max_dimension: int = Field(default_factory=lambda: int(os.environ["VISION_MAX_DIM"]))
    vision_min_dimension: int = Field(default_factory=lambda: int(os.environ["VISION_MIN_DIM"]))
    vision_preview_format: str = "jpeg"
    vision_preview_quality: int = 85


class WeatherConfig(BaseModel):
    provider: str = "open-meteo"
    latitude: float = -62.15
    longitude: float = -58.45
    schedule_hours: list[int] = Field(default_factory=lambda: [6, 12, 18, 0])


class RemoteSyncConfig(BaseModel):
    api_key_env: str = "REMOTE_SYNC_API_KEY"
    base_url: str = Field(default_factory=lambda: os.environ["REMOTE_SYNC_BASE_URL"])
    max_images_per_batch: int = 3
    max_images_per_day: int = 10

    @property
    def api_key(self) -> str:
        return os.environ[self.api_key_env]


class Config(BaseModel):
    agent: AgentConfig
    personality: PersonalityConfig
    actions: ActionsConfig = Field(default_factory=ActionsConfig)
    system_prompt: SystemPromptConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    http_server: HttpServerConfig = Field(default_factory=HttpServerConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    db: DbConfig = Field(default_factory=DbConfig)
    photo_pipeline: PhotoPipelineConfig = Field(default_factory=PhotoPipelineConfig)
    image_preprocessing: ImagePreprocessingConfig = Field(default_factory=ImagePreprocessingConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    remote_sync: RemoteSyncConfig = Field(default_factory=RemoteSyncConfig)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        with path.open() as f:
            data = json.load(f)
        return cls.model_validate(data)
