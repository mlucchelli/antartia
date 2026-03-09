from __future__ import annotations

from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "Database":
        await self.init_all_tables()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database not connected — call connect() or init_all_tables() first"
        return self._conn

    async def init_all_tables(self) -> None:
        if not self._conn:
            await self.connect()
        await self._create_locations_table()
        await self._create_photos_table()
        await self._create_weather_table()
        await self._create_tasks_table()
        await self._create_messages_table()
        await self._create_sessions_table()
        await self._create_knowledge_docs_table()
        await self._create_activity_logs_table()
        await self._create_token_usage_table()
        await self._create_reflections_table()
        await self._conn.commit()

    async def _create_locations_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                latitude    REAL    NOT NULL,
                longitude   REAL    NOT NULL,
                recorded_at TEXT    NOT NULL,
                received_at TEXT    NOT NULL
            )
        """)

    async def _create_photos_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path           TEXT    NOT NULL UNIQUE,
                file_name           TEXT    NOT NULL,
                folder              TEXT    NOT NULL,
                sha256              TEXT,
                created_at_fs       TEXT,
                discovered_at       TEXT    NOT NULL,
                processed           INTEGER NOT NULL DEFAULT 0,
                processed_at        TEXT,
                moved_to_path       TEXT,
                vision_status       TEXT    NOT NULL DEFAULT 'pending',
                vision_description  TEXT,
                vision_model        TEXT,
                significance_score  REAL,
                is_remote_candidate INTEGER NOT NULL DEFAULT 0,
                remote_uploaded     INTEGER NOT NULL DEFAULT 0,
                remote_uploaded_at  TEXT,
                remote_url          TEXT,
                original_width      INTEGER,
                original_height     INTEGER,
                vision_preview_path TEXT,
                vision_input_width  INTEGER,
                vision_input_height INTEGER,
                error_message       TEXT
            )
        """)

    async def _create_weather_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS weather_snapshots (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                latitude             REAL    NOT NULL,
                longitude            REAL    NOT NULL,
                temperature          REAL,
                apparent_temperature REAL,
                wind_speed           REAL,
                wind_gusts           REAL,
                wind_direction       REAL,
                precipitation        REAL,
                snowfall             REAL,
                snow_depth           REAL,
                surface_pressure     REAL,
                condition            TEXT,
                raw_json             TEXT,
                recorded_at          TEXT    NOT NULL
            )
        """)

    async def _create_tasks_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                type          TEXT    NOT NULL,
                payload       TEXT    NOT NULL DEFAULT '{}',
                status        TEXT    NOT NULL DEFAULT 'pending',
                priority      INTEGER NOT NULL DEFAULT 1,
                source        TEXT    NOT NULL DEFAULT 'agent',
                created_at    TEXT    NOT NULL,
                started_at    TEXT,
                executed_at   TEXT,
                error_message TEXT
            )
        """)
        # Migration: add source column to existing DBs that predate this field
        try:
            await self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN source TEXT NOT NULL DEFAULT 'agent'"
            )
        except Exception:
            pass  # column already exists

    async def _create_messages_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT    NOT NULL,
                role         TEXT    NOT NULL,
                content      TEXT    NOT NULL,
                timestamp    TEXT    NOT NULL,
                published    INTEGER NOT NULL DEFAULT 0,
                published_at TEXT
            )
        """)

    async def _create_sessions_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id            TEXT PRIMARY KEY,
                started_at    TEXT NOT NULL,
                last_activity TEXT NOT NULL
            )
        """)

    async def _create_activity_logs_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT,
                action_type TEXT NOT NULL,
                payload     TEXT,
                result      TEXT,
                created_at  TEXT NOT NULL
            )
        """)

    async def _create_token_usage_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id        TEXT,
                model             TEXT NOT NULL,
                call_type         TEXT NOT NULL,
                prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT NOT NULL
            )
        """)

    async def _create_reflections_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                date       TEXT    NOT NULL UNIQUE,
                content    TEXT    NOT NULL,
                word_count INTEGER,
                created_at TEXT    NOT NULL
            )
        """)

    async def _create_knowledge_docs_table(self) -> None:
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_docs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name   TEXT    NOT NULL UNIQUE,
                status      TEXT    NOT NULL DEFAULT 'pending',
                chunk_count INTEGER,
                error       TEXT,
                indexed_at  TEXT,
                created_at  TEXT    NOT NULL
            )
        """)
