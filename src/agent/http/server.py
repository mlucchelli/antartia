from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.locations_repo import LocationsRepository
from agent.db.tasks_repo import TasksRepository

logger = logging.getLogger(__name__)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, db: Database, output=None) -> None:
    try:
        raw = b""
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            raw += chunk
            if b"\r\n\r\n" in raw:
                break

        if not raw:
            writer.close()
            return

        header_part, _, body_start = raw.partition(b"\r\n\r\n")
        headers_text = header_part.decode(errors="replace")
        first_line = headers_text.split("\r\n")[0]
        parts = first_line.split(" ")

        if len(parts) < 2 or parts[0] != "POST" or parts[1] != "/locations":
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        content_length = 0
        for line in headers_text.split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break

        body = body_start
        remaining = content_length - len(body_start)
        if remaining > 0:
            body += await reader.read(remaining)

        logger.info("POST /locations raw body: %s", body.decode(errors="replace"))

        try:
            data = json.loads(body)
            if "location" in data:
                latitude = float(data["location"]["lat"])
                longitude = float(data["location"]["lng"])
            else:
                latitude = float(data["latitude"])
                longitude = float(data["longitude"])
            recorded_at_str = data.get("recorded_at")
            if recorded_at_str:
                recorded_at = datetime.fromisoformat(recorded_at_str.replace("Z", "+00:00"))
            else:
                recorded_at = datetime.now(timezone.utc)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            msg = f'{{"error": "{exc}"}}'
            response = (
                f"HTTP/1.1 400 Bad Request\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(msg)}\r\n\r\n{msg}"
            ).encode()
            writer.write(response)
            await writer.drain()
            writer.close()
            return

        locations = LocationsRepository(db)
        tasks = TasksRepository(db)

        loc = await locations.insert(latitude, longitude, recorded_at)
        await tasks.insert("process_location", {"location_id": loc["id"]})

        logger.info("Location received: lat=%s lon=%s id=%s", latitude, longitude, loc["id"])
        if output:
            output.update_location(latitude, longitude)

        msg = json.dumps({"status": "ok", "location_id": loc["id"]})
        response = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(msg)}\r\n\r\n{msg}"
        ).encode()
        writer.write(response)
        await writer.drain()

    except Exception as exc:
        logger.exception("HTTP handler error: %s", exc)
        writer.write(b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
    finally:
        writer.close()


async def start_http_server(config: Config, db: Database, output=None) -> asyncio.Server:
    host = config.http_server.host
    port = config.http_server.port

    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, db, output),
        host,
        port,
    )
    logger.info("HTTP server listening on %s:%s", host, port)
    return server
