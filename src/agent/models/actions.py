from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from agent.models.state import ConversationState


class Action(BaseModel, ABC):
    type: str
    payload: dict

    @abstractmethod
    async def execute(self, state: ConversationState) -> str | None: ...


# ── Display action (non-terminal) ─────────────────────────────────────────────

class SendMessagePayload(BaseModel):
    content: str


class SendMessageAction(Action):
    """Display text to the user. Does NOT terminate the chain."""
    type: str = "send_message"

    async def execute(self, state: ConversationState) -> str | None:
        p = SendMessagePayload.model_validate(self.payload)
        state.add_message("assistant", p.content)
        return p.content


# ── Terminal action ────────────────────────────────────────────────────────────

class FinishAction(Action):
    """Terminates the chain. Use when the response is complete."""
    type: str = "finish"

    async def execute(self, state: ConversationState) -> str | None:
        return None


# ── Expedition tool actions ───────────────────────────────────────────────────
# These are data containers only — execution is dispatched by the Runtime.

class ToolAction(Action, ABC):
    """Base for all expedition tool actions. execute() is handled by Runtime._dispatch_tool."""

    async def execute(self, state: ConversationState) -> str | None:
        return None  # never called directly


class GetLatestLocationsAction(ToolAction):
    type: str = "get_latest_locations"


class GetLocationsByDateAction(ToolAction):
    type: str = "get_locations_by_date"


class GetPhotosAction(ToolAction):
    type: str = "get_photos"


class GetWeatherAction(ToolAction):
    type: str = "get_weather"


class CreateTaskAction(ToolAction):
    type: str = "create_task"


class ScanPhotoInboxAction(ToolAction):
    type: str = "scan_photo_inbox"


class PublishDailyProgressAction(ToolAction):
    type: str = "publish_daily_progress"


class PublishRouteSnapshotAction(ToolAction):
    type: str = "publish_route_snapshot"


class UploadImageAction(ToolAction):
    type: str = "upload_image"


class PublishAgentMessageAction(ToolAction):
    type: str = "publish_agent_message"


class PublishWeatherSnapshotAction(ToolAction):
    type: str = "publish_weather_snapshot"


class SearchKnowledgeAction(ToolAction):
    type: str = "search_knowledge"


class IndexKnowledgeAction(ToolAction):
    type: str = "index_knowledge"


class AddKnowledgeAction(ToolAction):
    type: str = "add_knowledge"


class ClearKnowledgeAction(ToolAction):
    type: str = "clear_knowledge"
