"""原始媒体文件生命周期管理。

在任务完成 media_retention_hours 后自动删除原始音视频文件，
保留转写/评估/合规等 JSON 结果文件。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_KEEP_FILES = frozenset({
    "transcript.json",
    "evaluation.json",
    "compliance.json",
    "meta.json",
    "ocr_results.json",
    "visual_events.json",
})

_MEDIA_STEMS = frozenset({"audio", "video"})


class LifecycleService:
    """定期清理过期的原始媒体文件，保留任务结果 JSON。"""

    def __init__(self, upload_dir: Path, retention_hours: int) -> None:
        self._upload_dir = upload_dir
        self._retention = timedelta(hours=retention_hours)

    def cleanup_expired_media(self) -> int:
        """扫描并删除过期原始媒体文件，返回删除文件数。"""
        cutoff = datetime.now(timezone.utc) - self._retention
        deleted = 0

        for task_dir in self._upload_dir.iterdir():
            if not task_dir.is_dir():
                continue
            meta_path = task_dir / "meta.json"
            if not meta_path.exists():
                continue
            # 只清理已完成任务（transcript.json 存在表示转写成功）
            if not (task_dir / "transcript.json").exists():
                continue

            try:
                mtime = datetime.fromtimestamp(meta_path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if mtime > cutoff:
                continue

            for f in task_dir.iterdir():
                if f.is_file() and f.name not in _KEEP_FILES and f.stem in _MEDIA_STEMS:
                    f.unlink(missing_ok=True)
                    logger.info("Lifecycle: deleted raw media %s", f)
                    deleted += 1

        if deleted:
            logger.info("Lifecycle cleanup: %d raw media files removed", deleted)
        return deleted

    async def run_periodic(self, interval_seconds: int = 3600) -> None:
        """后台定时清理循环（通过 asyncio.create_task 在 lifespan 中启动）。"""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await asyncio.to_thread(self.cleanup_expired_media)
            except Exception as e:
                logger.warning("Lifecycle cleanup error: %s", e)
