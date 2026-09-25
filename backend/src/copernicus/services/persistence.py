"""任务结果与哈希去重索引的 JSON 文件持久化服务。"""

import json
import logging
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from copernicus.exceptions import InvalidIdentifierError

logger = logging.getLogger(__name__)

_FAILURE_FILE = "failure.json"

# task_id 为 uuid4().hex：32 位小写十六进制字符
_SAFE_TASK_ID = re.compile(r'^[0-9a-f]{32}$')


class PersistenceService:
    """管理 upload_dir/{task_id}/ 目录下的 JSON 持久化数据。"""

    def __init__(self, upload_dir: Path) -> None:
        self._upload_dir = upload_dir
        self._upload_dir.mkdir(parents=True, exist_ok=True)

    # -- directory helpers ---------------------------------------------------

    def task_dir(self, task_id: str) -> Path:
        if not _SAFE_TASK_ID.fullmatch(task_id):
            raise InvalidIdentifierError(f"Invalid task_id format: {task_id!r}")
        d = self._upload_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- JSON read / write ---------------------------------------------------

    def save_json(self, task_id: str, filename: str, model: BaseModel) -> None:
        dest = self.task_dir(task_id) / filename
        self._atomic_write(dest, model.model_dump_json(indent=2))
        logger.info("Persisted %s for task %s", filename, task_id)

    def save_dict(self, task_id: str, filename: str, data: dict) -> None:
        dest = self.task_dir(task_id) / filename
        self._atomic_write(dest, json.dumps(data, ensure_ascii=False, indent=2))
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

    def _task_dir_unchecked(self, task_id: str) -> Path:
        """返回 task 目录路径，验证格式但不创建目录（供只读查询用）。"""
        if not _SAFE_TASK_ID.fullmatch(task_id):
            raise InvalidIdentifierError(f"Invalid task_id format: {task_id!r}")
        return self._upload_dir / task_id

    def has_file(self, task_id: str, filename: str) -> bool:
        return (self._task_dir_unchecked(task_id) / filename).exists()

    def delete_file(self, task_id: str, filename: str) -> None:
        path = self._task_dir_unchecked(task_id) / filename
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

    def update_meta(self, task_id: str, **fields: str) -> bool:
        """合并更新 meta.json 中的字段；任务不存在返回 False。"""
        meta = self.load_meta(task_id) if self.has_file(task_id, "meta.json") else None
        if meta is None:
            return False
        meta.update(fields)
        self._atomic_write(
            self.task_dir(task_id) / "meta.json",
            json.dumps(meta, ensure_ascii=False, indent=2),
        )
        return True

    def delete_task(self, task_id: str) -> bool:
        """删除任务目录及其全部文件（原始媒体、结果、关键帧等）。"""
        d = self._task_dir_unchecked(task_id)
        if not d.is_dir():
            return False
        shutil.rmtree(d)
        logger.info("Purged task directory %s", task_id)
        return True

    # -- audio ---------------------------------------------------------------

    def save_audio(self, task_id: str, audio_bytes: bytes, suffix: str) -> Path:
        dest = self.task_dir(task_id) / f"audio{suffix}"
        dest.write_bytes(audio_bytes)
        logger.info("Saved audio (%d bytes) for task %s", len(audio_bytes), task_id)
        return dest

    def find_audio(self, task_id: str) -> Path | None:
        d = self._task_dir_unchecked(task_id)
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

    def persist_media(
        self,
        task_id: str,
        filename: str,
        file_hash: str,
        data: bytes,
        video_extensions: frozenset[str],
    ) -> Path:
        """保存媒体文件及 meta.json，返回保存路径。音频/视频自动按后缀区分。"""
        suffix = Path(filename).suffix or ".bin"
        if suffix.lower() in video_extensions:
            path = self.save_video(task_id, data, suffix)
            self.save_meta(
                task_id, filename=filename, file_hash=file_hash,
                audio_suffix=suffix, media_type="video", video_suffix=suffix,
            )
        else:
            path = self.save_audio(task_id, data, suffix)
            self.save_meta(task_id, filename=filename, file_hash=file_hash, audio_suffix=suffix)
        return path

    def find_video(self, task_id: str) -> Path | None:
        d = self._task_dir_unchecked(task_id)
        if not d.exists():
            return None
        for p in d.glob("video.*"):
            return p
        return None

    def frames_dir(self, task_id: str) -> Path:
        d = self.task_dir(task_id) / "frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- failure status ------------------------------------------------------

    def save_failure(self, task_id: str, error: str) -> None:
        """记录任务失败原因，供服务重启后恢复失败状态；仅对已有 meta.json 的任务生效。"""
        if not self.has_file(task_id, "meta.json"):
            return
        dest = self.task_dir(task_id) / _FAILURE_FILE
        self._atomic_write(
            dest,
            json.dumps(
                {"error": error, "failed_at": datetime.now(timezone.utc).isoformat()},
                ensure_ascii=False,
            ),
        )

    def load_failure_error(self, task_id: str) -> str | None:
        data = self.load_json(task_id, _FAILURE_FILE)
        return data.get("error") if data else None

    def clear_failure(self, task_id: str) -> None:
        self.delete_file(task_id, _FAILURE_FILE)

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
        """扫描 upload_dir，查找包含 meta.json 的任务目录。

        返回字典列表，键包含：task_id, meta, has_transcript,
        has_evaluation, has_compliance, audio_path。
        """
        results = [
            entry
            for d in self._upload_dir.iterdir()
            if d.is_dir() and (entry := self._scan_entry(d)) is not None
        ]
        logger.info("Scanned %d persisted tasks from disk", len(results))
        return results

    def scan_task(self, task_id: str) -> dict | None:
        """扫描单个任务目录，结构同 scan_completed_tasks 的条目；不存在返回 None。"""
        d = self._task_dir_unchecked(task_id)
        return self._scan_entry(d) if d.is_dir() else None

    def _scan_entry(self, d: Path) -> dict | None:
        meta_path = d / "meta.json"
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        task_id = d.name
        if not _SAFE_TASK_ID.fullmatch(task_id):
            return None
        audio_path = self.find_audio(task_id)
        video_path = self.find_video(task_id)
        frames_path = d / "frames"
        keyframe_count = sum(1 for p in frames_path.glob("*") if p.is_file()) if frames_path.is_dir() else 0
        return {
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

    # -- internal ------------------------------------------------------------

    @staticmethod
    def _atomic_write(dest: Path, content: str) -> None:
        """通过临时文件写入再重命名，防止部分写入导致数据损坏。"""
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
