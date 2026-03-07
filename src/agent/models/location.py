from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LocationRecord(BaseModel):
    id: int | None = None
    latitude: float
    longitude: float
    recorded_at: datetime
    received_at: datetime = Field(default_factory=_now)
