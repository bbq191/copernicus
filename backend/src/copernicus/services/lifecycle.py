"""磁盘生命周期管理。

- 已完成任务：超过 media_retention_hours 后删除原始音视频（保留转写/评估/合规等 JSON 与关键帧证据）
- 失败/被中断的任务：无任何可用结果，超期后整目录删除
- 中断的分片上传会话：超期后删除
- 存储配额：磁盘占用超过 max_storage_gb 时，按创建时间从旧到新删除原始媒体，直到回落到配额内
"""

import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MEDIA_STEMS = frozenset({"audio", "video", "synthesis"})
_SESSIONS_DIR = ".sessions"

# 失败任务与运行中任务在磁盘上无法区分，清理前至少等待这么久，避免误删仍在处理的任务
_MIN_FAILED_AGE = timedelta(hours=2)

_GB = 1024 ** 3


class LifecycleService:
    """定期清理过期与超配额的文件，保留任务结果。"""

    def __init__(
        self,
        upload_dir: Path,
        retention_hours: int,
        max_storage_gb: float = 0,
    ) -> None:
        self._upload_dir = upload_dir
        self._retention = timedelta(hours=retention_hours)
        self._max_storage_bytes = int(max_storage_gb * _GB)  # 0 表示不限制

    # ------------------------------------------------------------------ #
    #  扫描辅助
    # ------------------------------------------------------------------ #

    def _iter_tasks(self):
        """产出 (任务目录, 最近处理时间)；跳过隐藏目录与元数据缺失/损坏的目录。

        最近处理时间取 created_at 与重新转写时写入的 processed_at 中较晚者，
        保证被重跑的旧任务在处理期间不会因"已过期"而被清理。
        """
        for task_dir in self._upload_dir.iterdir():
            if not task_dir.is_dir() or task_dir.name.startswith("."):
                continue
            try:
                meta = json.loads((task_dir / "meta.json").read_text("utf-8"))
                times = [datetime.fromisoformat(meta["created_at"])]
                if meta.get("processed_at"):
                    times.append(datetime.fromisoformat(meta["processed_at"]))
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                continue
            yield task_dir, max(times)

    @staticmethod
    def _media_files(task_dir: Path) -> list[Path]:
        return [f for f in task_dir.iterdir() if f.is_file() and f.stem in _MEDIA_STEMS]

    @staticmethod
    def _delete_files(files: list[Path]) -> int:
        for f in files:
            f.unlink(missing_ok=True)
            logger.info("Lifecycle: deleted %s", f)
        return len(files)

    # ------------------------------------------------------------------ #
    #  清理策略
    # ------------------------------------------------------------------ #

    def cleanup_expired_media(self) -> int:
        """删除已完成且过期任务的原始媒体，返回删除文件数。"""
        cutoff = datetime.now(timezone.utc) - self._retention
        deleted = 0
        for task_dir, processed_at in self._iter_tasks():
            if processed_at > cutoff or not (task_dir / "transcript.json").exists():
                continue
            deleted += self._delete_files(self._media_files(task_dir))
        return deleted

    def cleanup_stale_failed_tasks(self) -> int:
        """整目录删除失败/被中断且超期的任务（没有转写结果，留着无用），返回删除任务数。"""
        cutoff = datetime.now(timezone.utc) - max(self._retention, _MIN_FAILED_AGE)
        removed = 0
        for task_dir, processed_at in self._iter_tasks():
            if processed_at > cutoff or (task_dir / "transcript.json").exists():
                continue
            shutil.rmtree(task_dir, ignore_errors=True)
            logger.info("Lifecycle: removed stale failed task %s", task_dir.name)
            removed += 1
        return removed

    def cleanup_stale_sessions(self) -> int:
        """删除超期未完成的分片上传会话，返回删除会话数。"""
        sessions_dir = self._upload_dir / _SESSIONS_DIR
        if not sessions_dir.is_dir():
            return 0
        cutoff = datetime.now(timezone.utc) - self._retention
        removed = 0
        for session in sessions_dir.iterdir():
            if not session.is_dir():
                continue
            modified = datetime.fromtimestamp(session.stat().st_mtime, tz=timezone.utc)
            if modified > cutoff:
                continue
            shutil.rmtree(session, ignore_errors=True)
            logger.info("Lifecycle: removed stale upload session %s", session.name)
            removed += 1
        return removed

    def enforce_storage_quota(self) -> int:
        """磁盘占用超过配额时，从最旧的任务开始删除原始媒体，返回删除文件数。"""
        if self._max_storage_bytes <= 0:
            return 0
        used = _dir_size(self._upload_dir)
        if used <= self._max_storage_bytes:
            return 0

        logger.warning(
            "Storage %.2f GB exceeds quota %.2f GB, evicting oldest media",
            used / _GB, self._max_storage_bytes / _GB,
        )
        deleted = 0
        for task_dir, _ in sorted(self._iter_tasks(), key=lambda t: t[1]):
            files = self._media_files(task_dir)
            if not files:
                continue
            used -= sum(f.stat().st_size for f in files)
            deleted += self._delete_files(files)
            if used <= self._max_storage_bytes:
                break
        return deleted

    def run_once(self) -> dict[str, int]:
        """依次执行全部清理策略并返回各项数量。"""
        result = {
            "expired_media": self.cleanup_expired_media(),
            "stale_failed_tasks": self.cleanup_stale_failed_tasks(),
            "stale_sessions": self.cleanup_stale_sessions(),
            "quota_evicted": self.enforce_storage_quota(),
        }
        if any(result.values()):
            logger.info("Lifecycle cleanup: %s", result)
        return result

    async def run_periodic(self, interval_seconds: int = 3600) -> None:
        """后台清理循环：启动时立即执行一次，之后每隔 interval_seconds 执行。"""
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except Exception as e:
                logger.warning("Lifecycle cleanup error: %s", e)
            await asyncio.sleep(interval_seconds)


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
