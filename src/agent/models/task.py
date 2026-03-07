from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

TASK_TYPES = {
    "process_location",
    "scan_photo_inbox",
    "process_photo",
    "fetch_weather",
    "publish_daily_progress",
    "publish_route_snapshot",
    "upload_image",
    "publish_agent_message",
    "publish_weather_snapshot",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRecord(BaseModel):
    id: int | None = None
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # pending | running | completed | failed
    priority: int = 1
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    executed_at: datetime | None = None
    error_message: str | None = None
