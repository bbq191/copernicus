"""JSON file persistence service for task results and hash dedup index."""

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PersistenceService:
    """Manages JSON persistence under ``upload_dir/{task_id}/``."""

    def __init__(self, upload_dir: Path) -> None:
        self._upload_dir = upload_dir
        self._upload_dir.mkdir(parents=True, exist_ok=True)

    # -- directory helpers ---------------------------------------------------

    def task_dir(self, task_id: str) -> Path:
        d = self._upload_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- JSON read / write ---------------------------------------------------

    def save_json(self, task_id: str, filename: str, model: BaseModel) -> None:
        dest = self.task_dir(task_id) / filename
        self._atomic_write(dest, model.model_dump_json(indent=2))
        logger.info("Persisted %s for task %s", filename, task_id)

    def load_json(self, task_id: str, filename: str) -> dict | None:
        path = self.task_dir(task_id) / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s for task %s: %s", filename, task_id, e)
            return None

    def has_file(self, task_id: str, filename: str) -> bool:
        return (self._upload_dir / task_id / filename).exists()

    def delete_file(self, task_id: str, filename: str) -> None:
        path = self._upload_dir / task_id / filename
        if path.exists():
            path.unlink()
            logger.info("Deleted %s for task %s", filename, task_id)

    # -- meta ----------------------------------------------------------------

    def save_meta(
        self,
        task_id: str,
        *,
        filename: str,
        file_hash: str,
        audio_suffix: str,
        media_type: str = "audio",
        video_suffix: str | None = None,
    ) -> None:
        meta: dict = {
            "filename": filename,
            "hash": file_hash,
            "audio_suffix": audio_suffix,
            "media_type": media_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if video_suffix:
            meta["video_suffix"] = video_suffix
        dest = self.task_dir(task_id) / "meta.json"
        self._atomic_write(dest, json.dumps(meta, ensure_ascii=False, indent=2))

    def load_meta(self, task_id: str) -> dict | None:
        return self.load_json(task_id, "meta.json")

    # -- audio ---------------------------------------------------------------

    def save_audio(self, task_id: str, audio_bytes: bytes, suffix: str) -> Path:
        dest = self.task_dir(task_id) / f"audio{suffix}"
        dest.write_bytes(audio_bytes)
        logger.info("Saved audio (%d bytes) for task %s", len(audio_bytes), task_id)
        return dest

    def find_audio(self, task_id: str) -> Path | None:
        d = self._upload_dir / task_id
        if not d.exists():
            return None
        for p in d.glob("audio.*"):
            return p
        # fallback: legacy path ./uploads/audio/{task_id}.*
        legacy_dir = self._upload_dir / "audio"
        if legacy_dir.exists():
            for p in legacy_dir.glob(f"{task_id}.*"):
                return p
        return None

    # -- video ---------------------------------------------------------------

    def save_video(self, task_id: str, video_bytes: bytes, suffix: str) -> Path:
        dest = self.task_dir(task_id) / f"video{suffix}"
        dest.write_bytes(video_bytes)
        logger.info("Saved video (%d bytes) for task %s", len(video_bytes), task_id)
        return dest

    def find_video(self, task_id: str) -> Path | None:
        d = self._upload_dir / task_id
        if not d.exists():
            return None
        for p in d.glob("video.*"):
            return p
        return None

    def frames_dir(self, task_id: str) -> Path:
        d = self.task_dir(task_id) / "frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- hash index ----------------------------------------------------------

    @property
    def _hash_index_path(self) -> Path:
        return self._upload_dir / "hash_index.json"

    def load_hash_index(self) -> dict[str, str]:
        if not self._hash_index_path.exists():
            return {}
        try:
            data = json.loads(self._hash_index_path.read_text("utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load hash index: %s", e)
        return {}

    def save_hash_index(self, index: dict[str, str]) -> None:
        self._atomic_write(
            self._hash_index_path,
            json.dumps(index, ensure_ascii=False, indent=2),
        )

    # -- scan ----------------------------------------------------------------

    def scan_completed_tasks(self) -> list[dict]:
        """Scan upload_dir for task directories containing meta.json.

        Returns a list of dicts with keys: task_id, meta, has_transcript,
        has_evaluation, has_compliance, audio_path.
        """
        results: list[dict] = []
        for d in self._upload_dir.iterdir():
            if not d.is_dir():
                continue
            meta_path = d / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            task_id = d.name
            audio_path = self.find_audio(task_id)
            video_path = self.find_video(task_id)
            frames_path = d / "frames"
            keyframe_count = len(list(frames_path.glob("*"))) if frames_path.is_dir() else 0
            results.append(
                {
                    "task_id": task_id,
                    "meta": meta,
                    "has_transcript": (d / "transcript.json").exists(),
                    "has_evaluation": (d / "evaluation.json").exists(),
                    "has_compliance": (d / "compliance.json").exists(),
                    "audio_path": str(audio_path) if audio_path else None,
                    "has_video": video_path is not None,
                    "keyframe_count": keyframe_count,
                    "has_ocr_results": (d / "ocr_results.json").exists(),
                    "has_visual_events": (d / "visual_events.json").exists(),
                }
            )
        logger.info("Scanned %d persisted tasks from disk", len(results))
        return results

    # -- internal ------------------------------------------------------------

    @staticmethod
    def _atomic_write(dest: Path, content: str) -> None:
        """Write via temp file + rename to avoid partial writes."""
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(dest.parent), suffix=".tmp"
        )
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp_path).replace(dest)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
