"""services/bulk_reaudit.py：规则变更后批量重跑受影响历史任务的合规审核。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from copernicus.schemas.task import TaskStatus
from copernicus.services.bulk_reaudit import (
    BulkReauditJob,
    ReauditDiff,
    _reaudit_one,
    _run,
    get_job,
    start_bulk_reaudit,
)

_TRANSCRIPT = {
    "transcript": [
        {"timestamp": "00:01", "timestamp_ms": 1000, "speaker": "A", "text_corrected": "你好"}
    ]
}


def _make_store(old_score: float, new_score: float, *, sub_status=TaskStatus.COMPLETED, sub_error=None):
    """load_json 对 compliance.json 的第一次调用返回旧分，之后都返回新分（模拟重审后已落盘更新）。"""
    store = MagicMock()
    calls = {"compliance": 0}

    def load_json(task_id, filename):
        if filename == "transcript.json":
            return _TRANSCRIPT
        if filename == "compliance.json":
            calls["compliance"] += 1
            score = old_score if calls["compliance"] == 1 else new_score
            return {"report": {"compliance_score": score}}
        return None

    store.persistence.load_json.side_effect = load_json
    store.submit_compliance_audit.return_value = "sub-task-1"
    store.get.return_value = SimpleNamespace(status=sub_status, error=sub_error)
    return store


async def _await_done(job: BulkReauditJob, timeout: float = 1.0) -> None:
    async def poll():
        while not job.done:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=timeout)


class TestReauditOne:
    async def test_records_a_diff_when_score_changes(self):
        store = _make_store(70.0, 85.0)
        job = BulkReauditJob(id="job-1", rule_id=1, task_ids=["task-a"])

        await _reaudit_one(store, job, "task-a")

        assert job.diffs == [ReauditDiff(task_id="task-a", old_score=70.0, new_score=85.0)]
        kwargs = store.submit_compliance_audit.call_args.kwargs
        assert kwargs["parent_task_id"] == "task-a"
        assert kwargs["use_rule_library"] is True

    async def test_no_diff_when_score_unchanged(self):
        store = _make_store(70.0, 70.0)
        job = BulkReauditJob(id="job-1", rule_id=1, task_ids=["task-a"])

        await _reaudit_one(store, job, "task-a")

        assert job.diffs == []

    async def test_raises_when_sub_task_failed(self):
        store = _make_store(70.0, 70.0, sub_status=TaskStatus.FAILED, sub_error="LLM 超时")
        job = BulkReauditJob(id="job-1", rule_id=1, task_ids=["task-a"])

        with pytest.raises(RuntimeError, match="LLM 超时"):
            await _reaudit_one(store, job, "task-a")

    async def test_raises_when_no_transcript(self):
        store = MagicMock()
        store.persistence.load_json.return_value = None
        job = BulkReauditJob(id="job-1", rule_id=1, task_ids=["task-a"])

        with pytest.raises(ValueError, match="transcript"):
            await _reaudit_one(store, job, "task-a")


class TestRun:
    async def test_processes_all_tasks_and_marks_done(self):
        store = _make_store(70.0, 70.0)
        job = BulkReauditJob(id="job-1", rule_id=1, task_ids=["task-a", "task-b"])

        await _run(store, job)

        assert job.done is True
        assert job.completed == 2
        assert job.failed == []

    async def test_one_failure_does_not_stop_the_rest(self, monkeypatch):
        calls: list[str] = []

        async def fake_reaudit_one(store, job, task_id):
            calls.append(task_id)
            if task_id == "task-a":
                raise RuntimeError("boom")

        monkeypatch.setattr("copernicus.services.bulk_reaudit._reaudit_one", fake_reaudit_one)

        job = BulkReauditJob(id="job-1", rule_id=1, task_ids=["task-a", "task-b"])
        await _run(MagicMock(), job)

        assert calls == ["task-a", "task-b"]
        assert job.failed == ["task-a"]
        assert job.completed == 2
        assert job.done is True


class TestJobRegistry:
    async def test_start_registers_the_job_and_runs_it_in_the_background(self):
        store = _make_store(70.0, 70.0)

        job = start_bulk_reaudit(store, rule_id=7, task_ids=["task-a"])

        assert get_job(job.id) is job
        assert job.rule_id == 7
        assert job.done is False  # 立即返回，不等待完成
        await _await_done(job)
        assert job.completed == 1

    async def test_unknown_job_id_returns_none(self):
        assert get_job("does-not-exist") is None
