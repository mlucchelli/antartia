from __future__ import annotations

import math
from datetime import datetime

from agent.db.database import Database
from agent.db.locations_repo import LocationsRepository


class DistanceService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _today_str(self) -> str:
        # Use system local timezone — the machine travels with the expedition
        return datetime.now().astimezone().strftime("%Y-%m-%d")

    async def _sum_distance(self, date_str: str) -> float:
        points = await LocationsRepository(self._db).get_by_date(date_str)
        if len(points) < 2:
            return 0.0
        total = sum(
            self._haversine(
                points[i - 1]["latitude"], points[i - 1]["longitude"],
                points[i]["latitude"],     points[i]["longitude"],
            )
            for i in range(1, len(points))
        )
        return round(total, 1)

    async def get_today_distance(self) -> float:
        return await self._sum_distance(self._today_str())

    async def get_distance_for_date(self, date_str: str) -> float:
        return await self._sum_distance(date_str)
