from __future__ import annotations

import logging

from agent.models.actions import (
    Action,
    AddKnowledgeAction,
    AddLocationAction,
    GetReflectionsAction,
    ClearKnowledgeAction,
    CreateTaskAction,
    FinishAction,
    GetLatestLocationsAction,
    GetLocationsByDateAction,
    GetDistanceAction,
    GetLogsAction,
    GetPhotosAction,
    GetTokenUsageAction,
    GetWeatherAction,
    IndexKnowledgeAction,
    PublishAgentMessageAction,
    PublishDailyProgressAction,
    PublishRouteSnapshotAction,
    PublishWeatherSnapshotAction,
    ScanPhotoInboxAction,
    SearchKnowledgeAction,
    SendMessageAction,
    UploadImageAction,
)

logger = logging.getLogger(__name__)

ACTION_REGISTRY: dict[str, type[Action]] = {
    "send_message": SendMessageAction,
    "finish": FinishAction,
    "get_latest_locations": GetLatestLocationsAction,
    "get_locations_by_date": GetLocationsByDateAction,
    "get_photos": GetPhotosAction,
    "get_weather": GetWeatherAction,
    "create_task": CreateTaskAction,
    "scan_photo_inbox": ScanPhotoInboxAction,
    "publish_daily_progress": PublishDailyProgressAction,
    "publish_route_snapshot": PublishRouteSnapshotAction,
    "upload_image": UploadImageAction,
    "publish_agent_message": PublishAgentMessageAction,
    "publish_weather_snapshot": PublishWeatherSnapshotAction,
    "search_knowledge": SearchKnowledgeAction,
    "index_knowledge": IndexKnowledgeAction,
    "add_knowledge": AddKnowledgeAction,
    "clear_knowledge": ClearKnowledgeAction,
    "get_logs": GetLogsAction,
    "get_token_usage": GetTokenUsageAction,
    "get_distance": GetDistanceAction,
    "add_location": AddLocationAction,
    "get_reflections": GetReflectionsAction,
}


class ActionParser:
    def parse(self, raw_actions: list[dict]) -> list[Action]:
        actions: list[Action] = []
        for raw in raw_actions:
            action_type = raw.get("type")
            if action_type not in ACTION_REGISTRY:
                logger.warning("Unknown action type: %s — skipping", action_type)
                continue
            cls = ACTION_REGISTRY[action_type]
            payload = raw.get("payload", {})
            actions.append(cls.model_validate({"type": action_type, "payload": payload}))
        return actions
