import json
from unittest.mock import MagicMock

import pytest

from copernicus.config import Settings
from copernicus.exceptions import TaskBusyError
from copernicus.schemas.task import TaskStatus
from copernicus.services.persistence import PersistenceService
from copernicus.services.task_store import TaskInfo, TaskStore

TID_DONE = "a" * 32
TID_LOST = "b" * 32  # 被重启打断：有媒体、无结果
TID_FAILED = "c" * 32  # 失败并留下原因
TID_EMPTY = "d" * 32  # 媒体已被清理，且无结果

_TRANSCRIPT = {
    "transcript": [
        {
            "timestamp": "00:00",
            "timestamp_ms": 0,
            "end_ms": 1000,
            "speaker": "Speaker 1",
            "text": "你好",
            "text_corrected": "你好",
        }
    ],
    "processing_time_ms": 1.0,
}


@pytest.fixture
def persistence(tmp_path) -> PersistenceService:
    return PersistenceService(tmp_path)


def _make_task_dir(
    persistence: PersistenceService, task_id: str, *, file_hash: str, media: bool = True
) -> None:
    persistence.save_meta(
        task_id, filename="a.wav", file_hash=file_hash, audio_suffix=".wav"
    )
    if media:
        persistence.save_audio(task_id, b"audio", ".wav")


@pytest.fixture
def store(persistence: PersistenceService) -> TaskStore:
    return TaskStore(MagicMock(), persistence, Settings())


class TestRestoreFromDisk:
    def test_completed_task_restored_as_completed(self, persistence, store):
        _make_task_dir(persistence, TID_DONE, file_hash="h1")
        persistence.save_dict(TID_DONE, "transcript.json", _TRANSCRIPT)

        store.restore_from_disk()

        assert store.get(TID_DONE).status == TaskStatus.COMPLETED

    def test_interrupted_task_restored_as_failed_not_404(self, persistence, store):
        _make_task_dir(persistence, TID_LOST, file_hash="h2")

        store.restore_from_disk()

        task = store.get(TID_LOST)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert "中断" in task.error

    def test_persisted_failure_reason_survives_restart(self, persistence, store):
        _make_task_dir(persistence, TID_FAILED, file_hash="h3")
        persistence.save_failure(TID_FAILED, "ASR 崩溃")

        store.restore_from_disk()

        assert store.get(TID_FAILED).error == "ASR 崩溃"

    def test_task_without_media_or_result_not_restored(self, persistence, store):
        _make_task_dir(persistence, TID_EMPTY, file_hash="h4", media=False)

        store.restore_from_disk()

        assert store.get(TID_EMPTY) is None


class TestFailurePersistence:
    def test_mark_failed_writes_failure_file(self, persistence, store):
        _make_task_dir(persistence, TID_LOST, file_hash="h")
        task = TaskInfo(TID_LOST)
        store._tasks[TID_LOST] = task

        store._mark_failed(task, "boom")

        assert task.status == TaskStatus.FAILED
        assert persistence.load_failure_error(TID_LOST) == "boom"

    def test_failure_not_persisted_for_task_without_meta(self, persistence, store):
        # 文本评估子任务没有自己的目录，不应凭空创建目录
        task = TaskInfo("e" * 32)
        store._mark_failed(task, "boom")

        assert not (persistence._upload_dir / ("e" * 32)).exists()


class TestLazyRestore:
    def test_evicted_task_recovered_from_disk(self, persistence, store):
        _make_task_dir(persistence, TID_DONE, file_hash="h1")
        persistence.save_dict(TID_DONE, "transcript.json", _TRANSCRIPT)
        # 未调用 restore_from_disk，模拟任务已被内存淘汰

        task = store.get(TID_DONE)

        assert task is not None and task.status == TaskStatus.COMPLETED

    def test_invalidated_task_not_resurrected(self, persistence, store):
        _make_task_dir(persistence, TID_DONE, file_hash="h1")
        persistence.save_dict(TID_DONE, "transcript.json", _TRANSCRIPT)
        store.restore_from_disk()

        store.invalidate_task(TID_DONE)

        assert store.get(TID_DONE) is None

    def test_malformed_task_id_returns_none(self, store):
        assert store.get("../evil") is None


class TestHashLookup:
    def test_failed_task_is_not_reused_for_same_file(self, persistence, store):
        _make_task_dir(persistence, TID_LOST, file_hash="hx")
        store.restore_from_disk()
        assert store.get(TID_LOST).status == TaskStatus.FAILED

        assert store.lookup_by_hash("hx") is None


class TestRerunGuard:
    def test_rerun_rejected_while_running(self, persistence, store):
        _make_task_dir(persistence, TID_LOST, file_hash="h")
        running = TaskInfo(TID_LOST)
        running.status = TaskStatus.PROCESSING_ASR
        store._tasks[TID_LOST] = running

        with pytest.raises(TaskBusyError):
            store.rerun_transcript(TID_LOST)
