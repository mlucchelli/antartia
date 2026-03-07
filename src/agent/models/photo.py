from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PhotoRecord(BaseModel):
    id: int | None = None
    file_path: str
    file_name: str
    folder: str
    sha256: str | None = None
    created_at_fs: datetime | None = None
    discovered_at: datetime = Field(default_factory=_now)
    processed: bool = False
    processed_at: datetime | None = None
    moved_to_path: str | None = None
    vision_status: str = "pending"  # pending | running | completed | failed
    vision_description: str | None = None
    vision_model: str | None = None
    significance_score: float | None = None
    is_remote_candidate: bool = False
    remote_uploaded: bool = False
    remote_uploaded_at: datetime | None = None
    remote_url: str | None = None
    original_width: int | None = None
    original_height: int | None = None
    vision_preview_path: str | None = None
    vision_input_width: int | None = None
    vision_input_height: int | None = None
    error_message: str | None = None
