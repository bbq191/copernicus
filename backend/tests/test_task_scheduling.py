import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copernicus.config import Settings
from copernicus.error_handlers import register_error_handlers
from copernicus.exceptions import QueueFullError, TaskBusyError, TaskNotFoundError
from copernicus.routers.task import router as task_router
from copernicus.schemas.task import TaskStatus
from copernicus.services.persistence import PersistenceService
from copernicus.services.task_store import TaskInfo, TaskStore


def _store(tmp_path, *, max_active=2, evaluator=None) -> TaskStore:
    return TaskStore(
        MagicMock(),
        PersistenceService(tmp_path),
        Settings(task_max_active=max_active),
        evaluator=evaluator,
    )


def _fill(store: TaskStore, n: int, *, status=TaskStatus.PROCESSING_ASR, eval_only=False):
    for i in range(n):
        tid = f"{len(store._tasks):032x}"
        t = TaskInfo(tid, eval_only=eval_only)
        t.status = status
        store._tasks[tid] = t


class TestCapacity:
    def test_rejects_when_active_media_tasks_reach_limit(self, tmp_path):
        store = _store(tmp_path, max_active=2)
        _fill(store, 2)
        with pytest.raises(QueueFullError):
            store.ensure_capacity()

    def test_finished_tasks_do_not_count(self, tmp_path):
        store = _store(tmp_path, max_active=2)
        _fill(store, 5, status=TaskStatus.COMPLETED)
        _fill(store, 5, status=TaskStatus.FAILED)
        store.ensure_capacity()

    def test_llm_only_tasks_do_not_count(self, tmp_path):
        store = _store(tmp_path, max_active=1)
        _fill(store, 5, status=TaskStatus.EVALUATING, eval_only=True)
        store.ensure_capacity()

    def test_zero_means_unlimited(self, tmp_path):
        store = _store(tmp_path, max_active=0)
        _fill(store, 50)
        store.ensure_capacity()

    async def test_submit_rejected_before_creating_task(self, tmp_path):
        store = _store(tmp_path, max_active=1)
        _fill(store, 1)
        before = len(store._tasks)
        with pytest.raises(QueueFullError):
            store.submit_transcript(b"audio", "a.wav")
        assert len(store._tasks) == before

    def test_router_maps_queue_full_to_429(self, tmp_path):
        store = _store(tmp_path, max_active=1)
        _fill(store, 1)
        app = FastAPI()
        app.state.task_store = store
        app.include_router(task_router)
        register_error_handlers(app)

        r = TestClient(app).post(
            "/api/v1/tasks/transcript",
            files={"file": ("a.wav", b"audio-bytes", "audio/wav")},
        )

        assert r.status_code == 429


class TestCancel:
    async def _start_slow_evaluation(self, store, evaluator) -> str:
        started = asyncio.Event()

        async def slow(*args, **kwargs):
            started.set()
            await asyncio.sleep(30)

        evaluator.evaluate = AsyncMock(side_effect=slow)
        task_id = store.submit_text_evaluation("一些文本")
        await asyncio.wait_for(started.wait(), 2)
        return task_id

    async def test_cancel_llm_stage_marks_failed_and_frees_handle(self, tmp_path):
        evaluator = MagicMock()
        store = _store(tmp_path, evaluator=evaluator)
        task_id = await self._start_slow_evaluation(store, evaluator)
        handle = store._handles[task_id]

        store.cancel_task(task_id)
        await asyncio.gather(handle, return_exceptions=True)

        task = store.get(task_id)
        assert task.status == TaskStatus.FAILED
        assert "取消" in task.error
        assert task_id not in store._handles

    async def test_asr_stage_cannot_be_cancelled(self, tmp_path):
        store = _store(tmp_path)
        tid = "a" * 32
        task = TaskInfo(tid)
        task.status = TaskStatus.PROCESSING_ASR
        store._tasks[tid] = task
        store._handles[tid] = MagicMock()

        with pytest.raises(TaskBusyError):
            store.cancel_task(tid)
        store._handles[tid].cancel.assert_not_called()

    def test_cancel_unknown_task(self, tmp_path):
        with pytest.raises(TaskNotFoundError):
            _store(tmp_path).cancel_task("f" * 32)

    def test_cancel_finished_task_rejected(self, tmp_path):
        store = _store(tmp_path)
        tid = "b" * 32
        done = TaskInfo(tid)
        done.status = TaskStatus.COMPLETED
        store._tasks[tid] = done
        with pytest.raises(TaskBusyError):
            store.cancel_task(tid)

    async def test_cancel_all_stops_background_work(self, tmp_path):
        evaluator = MagicMock()
        store = _store(tmp_path, evaluator=evaluator)
        task_id = await self._start_slow_evaluation(store, evaluator)

        await store.cancel_all()

        assert store.get(task_id).status == TaskStatus.FAILED
        assert store._handles == {}
