from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx

from agent.config.loader import Config
from agent.db.database import Database
from agent.db.photos_repo import PhotosRepository
from agent.db.tasks_repo import TasksRepository
from agent.llm.ollama_vision import OllamaVisionClient
from agent.runtime.protocols import OutputHandler
from agent.services.image_preprocessing import ImagePreprocessingService

logger = logging.getLogger(__name__)


class PhotoService:
    """
    Full photo pipeline:
      1. scan_inbox — discover new files in inbox, insert DB rows, create process_photo tasks
      2. process_photo — preprocess → vision analysis → significance scoring → move original
    """

    def __init__(self, config: Config, db: Database, output: OutputHandler) -> None:
        self._config = config
        self._db = db
        self._output = output
        self._inbox = Path(config.photo_pipeline.inbox_dir)
        self._processed_dir = Path(config.photo_pipeline.processed_dir)
        self._processed_dir.mkdir(parents=True, exist_ok=True)
        self._preprocessor = ImagePreprocessingService(config)
        self._vision = OllamaVisionClient(config)
        self._threshold = config.photo_pipeline.significance_threshold

    async def scan_inbox(self) -> int:
        """Discover new photos in inbox, insert into DB, queue process_photo tasks."""
        photos_repo = PhotosRepository(self._db)
        tasks_repo = TasksRepository(self._db)

        image_files: list[Path] = []
        for pattern in ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG", "*.png", "*.PNG"):
            image_files.extend(self._inbox.glob(pattern))

        count = 0
        for path in sorted(image_files):
            existing = await photos_repo.get_by_path(str(path))
            if existing:
                continue

            self._output.on_task_progress(f"inbox: found new photo — {path.name}")
            photo = await photos_repo.insert(
                file_path=str(path),
                file_name=path.name,
                folder=str(self._inbox),
            )
            await tasks_repo.insert("process_photo", {"photo_id": photo["id"]})
            count += 1

        return count

    async def process_photo(self, photo_id: int) -> None:
        """Preprocess → vision → score → persist → move original."""
        photos_repo = PhotosRepository(self._db)
        photo = await photos_repo.get_by_id(photo_id)
        if photo is None:
            raise ValueError(f"Photo {photo_id} not found in DB")

        source_path = Path(photo["file_path"])
        filename = photo["file_name"]

        # ── Step 1: preprocess ────────────────────────────────────────────────
        self._output.on_task_progress(f"preprocessing: {filename}")
        preprocess = self._preprocessor.process(source_path)

        await photos_repo.update(
            photo_id,
            sha256=preprocess.sha256,
            original_width=preprocess.original_width,
            original_height=preprocess.original_height,
            vision_preview_path=str(preprocess.preview_path),
            vision_input_width=preprocess.preview_width,
            vision_input_height=preprocess.preview_height,
            vision_status="analyzing",
        )

        # ── Step 2: vision analysis ───────────────────────────────────────────
        self._output.on_vision_start(filename)
        vision_result = await self._vision.describe(preprocess.preview_path)
        self._output.on_task_progress(f"  ◈ {vision_result.summary}")

        # ── Step 3: significance scoring ──────────────────────────────────────
        self._output.on_task_progress(f"scoring: {filename}")
        score = await self._score_significance(vision_result.description)
        is_candidate = score >= self._threshold
        self._output.on_task_progress(
            f"  score={score:.2f} — "
            f"{'✓ remote candidate' if is_candidate else '✗ below threshold'}"
        )

        # ── Step 4: move original to processed/ ───────────────────────────────
        moved_path = self._processed_dir / filename
        if source_path.exists():
            shutil.move(str(source_path), str(moved_path))
            self._output.on_task_progress(f"  moved: {filename} → processed/")

        # ── Step 5: update DB ─────────────────────────────────────────────────
        await photos_repo.update(
            photo_id,
            vision_status="done",
            vision_description=vision_result.description,
            vision_model=self._config.agent.vision_model,
            significance_score=score,
            is_remote_candidate=1 if is_candidate else 0,
            processed=1,
            processed_at=datetime.now(timezone.utc).isoformat(),
            moved_to_path=str(moved_path),
        )

    async def _score_significance(self, description: str) -> float:
        """Score description significance via Ollama. Returns 0.0–1.0."""
        prompt = self._config.photo_pipeline.scoring_prompt + description

        body = {
            "model": self._config.agent.vision_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._config.photo_pipeline.ollama_url}/api/generate",
                    json=body,
                    timeout=60.0,
                )
                resp.raise_for_status()

            raw = resp.json().get("response", "").strip()
            data = json.loads(raw)
            score = float(data.get("significance_score", 0.5))
            return max(0.0, min(1.0, score))

        except Exception as exc:
            logger.warning("Significance scoring failed (%s) — defaulting to 0.5", exc)
            return 0.5
