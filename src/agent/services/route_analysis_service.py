from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agent.db.database import Database
from agent.db.locations_repo import LocationsRepository
from agent.db.weather_repo import WeatherRepository

logger = logging.getLogger(__name__)

# Candidate landing sites — OTL31a26 expedition (Antarctic Sound / Weddell Sea)
LANDING_SITES: list[dict] = [
    {"name": "Antarctic Sound",       "lat": -63.433, "lon": -56.650},
    {"name": "Brown Bluff",           "lat": -63.533, "lon": -56.917},
    {"name": "Paulet Island",         "lat": -63.583, "lon": -55.783},
    {"name": "Devil Island",          "lat": -63.800, "lon": -57.283},
    {"name": "Hope Bay",              "lat": -63.383, "lon": -56.983},
    {"name": "Gourdin Island",        "lat": -63.200, "lon": -57.300},
    {"name": "Jonassen Island",       "lat": -63.550, "lon": -56.667},
    {"name": "Andersson Island",      "lat": -63.583, "lon": -56.583},
    {"name": "Seymour Island",        "lat": -64.233, "lon": -56.617},
    {"name": "Eagle Island",          "lat": -63.667, "lon": -57.483},
    {"name": "Ushuaia",               "lat": -54.800, "lon": -68.300},
]

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


@dataclass
class NearestSite:
    name: str
    distance_km: float
    bearing_deg: float
    bearing_compass: str
    eta_hours: float | None = None  # filled in if avg_speed > 0


@dataclass
class RouteAnalysis:
    analyzed_at: str
    date: str
    # current position
    latitude: float | None
    longitude: float | None
    point_count: int
    # movement
    bearing_deg: float | None
    bearing_compass: str | None
    speed_kmh: float | None        # last segment
    avg_speed_kmh: float | None    # avg over all today's segments
    distance_km: float             # total today
    stopped: bool                  # last segment speed < 0.5 km/h
    # wind
    wind_speed_kmh: float | None
    wind_direction_deg: float | None
    wind_angle_label: str | None   # headwind / beam reach / tailwind
    # defaults
    window_hours: int = 12
    nearest_sites: list[NearestSite] = field(default_factory=list)

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(f"Route analysis — {self.analyzed_at} UTC  (today since 00:00 local)")
        if self.latitude is not None:
            lines.append(f"Position: {self.latitude:.4f}, {self.longitude:.4f}  ({self.point_count} fix(es) today)")
        else:
            lines.append("Position: no GPS data today")

        if self.bearing_deg is not None:
            lines.append(
                f"Heading: {self.bearing_compass} ({self.bearing_deg:.0f}°)"
                f"  ·  speed now {self.speed_kmh:.1f} km/h"
                f"  ·  avg {self.avg_speed_kmh:.1f} km/h"
                f"  ·  {'stopped' if self.stopped else 'underway'}"
            )
        lines.append(f"Distance today: {self.distance_km:.1f} km")

        if self.wind_direction_deg is not None:
            lines.append(
                f"Wind: {self.wind_speed_kmh:.0f} km/h from {_compass(self.wind_direction_deg)}"
                f" ({self.wind_direction_deg:.0f}°)"
                + (f"  →  {self.wind_angle_label}" if self.wind_angle_label else "")
            )

        if self.nearest_sites:
            lines.append("Nearest candidate sites:")
            for s in self.nearest_sites:
                eta = f"  ETA ~{s.eta_hours:.1f}h" if s.eta_hours is not None else ""
                lines.append(f"  {s.name:<22} {s.distance_km:>6.1f} km  {s.bearing_compass} ({s.bearing_deg:.0f}°){eta}")

        return "\n".join(lines)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _compass(deg: float) -> str:
    return _COMPASS[round(deg / 22.5) % 16]


def _wind_angle_label(wind_dir: float, heading: float) -> str:
    angle = (wind_dir - heading + 360) % 360
    if angle > 180:
        angle = 360 - angle
    if angle < 45:
        return "headwind"
    if angle < 135:
        return "beam reach"
    return "tailwind"


class RouteAnalysisService:
    def __init__(self, db: Database, timezone: str = "UTC") -> None:
        self._db = db
        self._timezone = timezone

    async def analyze(self, hours: int = 12) -> RouteAnalysis:
        tz = ZoneInfo(self._timezone)
        now_local = datetime.now(tz=tz)
        today_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        since_iso = today_midnight.isoformat()
        hours = max(1, int((now_local - today_midnight).total_seconds() / 3600))
        date = now_local.strftime("%Y-%m-%d")
        now_utc = datetime.now(timezone.utc)
        now_label = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        points = await LocationsRepository(self._db).get_since(since_iso)
        if len(points) < 3:
            raise ValueError(
                f"not enough GPS points in the last {hours}h window "
                f"({len(points)} found, need at least 3) — skipping analysis"
            )
        weather = await WeatherRepository(self._db).get_latest()

        # ── position ──────────────────────────────────────────────────────────
        lat = lon = None
        if points:
            lat = points[-1]["latitude"]
            lon = points[-1]["longitude"]

        # ── movement ──────────────────────────────────────────────────────────
        bearing_deg = bearing_compass = speed_kmh = avg_speed_kmh = None
        distance_km = 0.0
        stopped = False

        if len(points) >= 2:
            segments: list[tuple[float, float]] = []  # (km, hours)
            for i in range(1, len(points)):
                p0, p1 = points[i - 1], points[i]
                km = _haversine(p0["latitude"], p0["longitude"], p1["latitude"], p1["longitude"])
                distance_km += km
                try:
                    t0 = datetime.fromisoformat(p0["recorded_at"].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(p1["recorded_at"].replace("Z", "+00:00"))
                    hrs = (t1 - t0).total_seconds() / 3600
                    if hrs > 0:
                        segments.append((km, hrs))
                except Exception:
                    pass

            # bearing & speed from last two points
            p0, p1 = points[-2], points[-1]
            bearing_deg = _bearing(p0["latitude"], p0["longitude"], p1["latitude"], p1["longitude"])
            bearing_compass = _compass(bearing_deg)

            if segments:
                last_km, last_hrs = segments[-1]
                speed_kmh = round(last_km / last_hrs, 1) if last_hrs > 0 else 0.0
                total_hrs = sum(h for _, h in segments)
                avg_speed_kmh = round(distance_km / total_hrs, 1) if total_hrs > 0 else 0.0
                stopped = speed_kmh < 0.5

            distance_km = round(distance_km, 1)

        # ── wind ──────────────────────────────────────────────────────────────
        wind_speed = wind_dir = wind_label = None
        if weather:
            wind_speed = weather.get("wind_speed")
            wind_dir = weather.get("wind_direction")
            if wind_dir is not None and bearing_deg is not None:
                wind_label = _wind_angle_label(wind_dir, bearing_deg)

        # ── nearest sites ─────────────────────────────────────────────────────
        nearest: list[NearestSite] = []
        if lat is not None:
            for site in LANDING_SITES:
                dist = round(_haversine(lat, lon, site["lat"], site["lon"]), 1)
                brg = _bearing(lat, lon, site["lat"], site["lon"])
                eta = round(dist / avg_speed_kmh, 1) if avg_speed_kmh and avg_speed_kmh > 0.5 else None
                nearest.append(NearestSite(
                    name=site["name"],
                    distance_km=dist,
                    bearing_deg=round(brg, 0),
                    bearing_compass=_compass(brg),
                    eta_hours=eta,
                ))
            nearest.sort(key=lambda s: s.distance_km)
            nearest = nearest[:5]

        return RouteAnalysis(
            analyzed_at=now_label,
            date=date,
            window_hours=hours,
            latitude=lat,
            longitude=lon,
            point_count=len(points),
            bearing_deg=round(bearing_deg, 1) if bearing_deg is not None else None,
            bearing_compass=bearing_compass,
            speed_kmh=speed_kmh,
            avg_speed_kmh=avg_speed_kmh,
            distance_km=distance_km,
            stopped=stopped,
            wind_speed_kmh=wind_speed,
            wind_direction_deg=wind_dir,
            wind_angle_label=wind_label,
            nearest_sites=nearest,
        )
