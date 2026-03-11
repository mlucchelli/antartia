from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agent.config.loader import Config

VALID_TAGS: frozenset[str] = frozenset({
    "wildlife", "penguin", "seal", "cetacean", "orca", "seabird",
    "albatross", "skua", "leopard-seal", "landscape", "iceberg",
    "sea-ice", "glacier", "mountain", "beach", "underwater",
    "weather", "storm", "fog", "aurora", "sunset", "sunrise",
    "human", "ship", "zodiac", "equipment", "science", "landing",
    "antartia", "base",
})
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
      2. process_photo — preprocess → vision+scoring (single call) → move original
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
        for pattern in ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG", "*.png", "*.PNG", "*.webp", "*.WEBP"):
            image_files.extend(self._inbox.glob(pattern))

        logger.info("Photo inbox: scanning %s — %d file(s) found", self._inbox.resolve(), len(image_files))

        count = 0
        for path in sorted(image_files):
            existing = await photos_repo.get_by_path(str(path))
            if existing:
                logger.debug("Photo inbox: skip %s (already in DB id=%s)", path.name, existing.get("id"))
                continue

            self._output.on_task_progress(f"inbox: found new photo — {path.name}")
            logger.info("Photo inbox: queued %s for processing", path.name)
            photo = await photos_repo.insert(
                file_path=str(path),
                file_name=path.name,
                folder=str(self._inbox),
            )
            await tasks_repo.insert("process_photo", {"photo_id": photo["id"]})
            count += 1

        return count

    async def process_photo(self, photo_id: int) -> None:
        """Preprocess → vision+scoring (single call) → persist → move original."""
        from agent.db.token_usage_repo import TokenUsageRepository
        token_repo = TokenUsageRepository(self._db)
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

        # ── Step 2: vision + scoring (single model call) ──────────────────────
        self._output.on_vision_start(filename)
        logger.info("Photo vision: analyzing %s", filename)
        vision_result = await self._vision.describe(preprocess.preview_path)
        logger.info(
            "Photo vision: done %s — score=%.2f tags=%s quote=%s",
            filename, vision_result.significance_score, vision_result.tags,
            f'"{vision_result.agent_quote[:60]}"' if vision_result.agent_quote else "none",
        )

        total_tokens = (
            vision_result.usage.get("prompt_tokens", 0)
            + vision_result.usage.get("completion_tokens", 0)
        )
        await token_repo.insert(
            model=self._config.agent.vision_model,
            call_type="vision",
            prompt_tokens=vision_result.usage.get("prompt_tokens", 0),
            completion_tokens=vision_result.usage.get("completion_tokens", 0),
        )
        if total_tokens:
            self._output.on_tokens_used(total_tokens)

        score = vision_result.significance_score
        tags = [t for t in vision_result.tags if t in VALID_TAGS]
        is_candidate = score >= self._threshold

        # ── Vision result display block ───────────────────────────────────────
        score_bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
        candidate_label = "✓ candidate" if is_candidate else "✗ below threshold"
        self._output.on_task_progress(f"  ┌─ {filename}")
        # wrap description at ~90 chars
        desc = vision_result.description or vision_result.summary
        words = desc.split()
        line, lines = [], []
        for w in words:
            line.append(w)
            if len(" ".join(line)) >= 88:
                lines.append(" ".join(line))
                line = []
        if line:
            lines.append(" ".join(line))
        for i, l in enumerate(lines):
            prefix = "  │  " if i < len(lines) - 1 else "  │  "
            self._output.on_task_progress(f"{prefix}{l}")
        if tags:
            self._output.on_task_progress(f"  │  tags: {', '.join(tags)}")
        if vision_result.agent_quote:
            self._output.on_task_progress(f"  │  quote: \"{vision_result.agent_quote}\"")
        self._output.on_task_progress(
            f"  └─ score: {score:.2f} [{score_bar}] {candidate_label}"
        )

        # ── Step 3: move original to processed/ ───────────────────────────────
        moved_path = self._processed_dir / filename
        if source_path.exists():
            shutil.move(str(source_path), str(moved_path))
            self._output.on_task_progress(f"  moved: {filename} → processed/")
            logger.info("Photo moved: %s → processed/", filename)

        # ── Step 4: update DB ─────────────────────────────────────────────────
        from agent.db.locations_repo import LocationsRepository
        latest_locs = await LocationsRepository(self._db).get_latest(limit=1)
        lat = latest_locs[0]["latitude"] if latest_locs else None
        lon = latest_locs[0]["longitude"] if latest_locs else None

        await photos_repo.update(
            photo_id,
            vision_status="done",
            vision_description=vision_result.description,
            vision_model=self._config.agent.vision_model,
            significance_score=score,
            is_remote_candidate=1 if is_candidate else 0,
            agent_quote=vision_result.agent_quote,
            tags=json.dumps(tags) if tags else None,
            processed=1,
            processed_at=datetime.now(timezone.utc).isoformat(),
            moved_to_path=str(moved_path),
            latitude=lat,
            longitude=lon,
        )

        if is_candidate:
            tasks_repo = TasksRepository(self._db)
            await tasks_repo.insert("upload_image", {"photo_id": photo_id})
            logger.info("Photo upload queued: photo_id=%d (%s)", photo_id, filename)
