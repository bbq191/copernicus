"""规则库规则变更后，批量重跑受影响历史任务的合规审核。

单进程单 worker 部署下，合规审核的 LLM 调用和实时的转写/合规请求共享同一个事件循环
（本地 Ollama 时还共享同一块 GPU）；批量重审因此必须串行执行、一次只带一个任务在跑，
不能把受影响的历史任务一次性全丢进去并发审核，否则会和正在使用系统的用户抢资源。

任务级别的结果本身是持久化的（compliance.json 落盘在各自任务目录下，重启不丢），
这里的 Job 只是"这次批量重审跑到哪了"的进度追踪，纯内存、不落盘——服务重启会丢，
但丢的只是进度条，不是审核结果，可接受。

Author: afu
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from copernicus.schemas.task import TaskStatus
from copernicus.services.task_state import TERMINAL_STATUSES
from copernicus.services.task_store import TaskStore

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 2.0


@dataclass
class ReauditDiff:
    task_id: str
    old_score: float
    new_score: float


@dataclass
class BulkReauditJob:
    id: str
    rule_id: int
    task_ids: list[str]
    completed: int = 0
    failed: list[str] = field(default_factory=list)
    diffs: list[ReauditDiff] = field(default_factory=list)
    done: bool = False
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# 进程内存，不落盘：见模块说明。key 是 job.id。
_jobs: dict[str, BulkReauditJob] = {}


def get_job(job_id: str) -> BulkReauditJob | None:
    return _jobs.get(job_id)


def start_bulk_reaudit(store: TaskStore, rule_id: int, task_ids: list[str]) -> BulkReauditJob:
    """登记一个批量重审 Job 并在后台串行跑起来，立即返回（不等待完成）。"""
    job = BulkReauditJob(id=uuid.uuid4().hex, rule_id=rule_id, task_ids=list(task_ids))
    _jobs[job.id] = job
    asyncio.create_task(_run(store, job))
    return job


async def _run(store: TaskStore, job: BulkReauditJob) -> None:
    for task_id in job.task_ids:
        try:
            await _reaudit_one(store, job, task_id)
        except Exception:
            logger.warning("Bulk reaudit %s: task %s failed", job.id, task_id, exc_info=True)
            job.failed.append(task_id)
        finally:
            job.completed += 1
    job.done = True
    logger.info(
        "Bulk reaudit %s done: %d/%d tasks, %d failed, %d score changes",
        job.id, job.completed, len(job.task_ids), len(job.failed), len(job.diffs),
    )


async def _reaudit_one(store: TaskStore, job: BulkReauditJob, task_id: str) -> None:
    old_data = store.persistence.load_json(task_id, "compliance.json")
    old_score = old_data["report"]["compliance_score"] if old_data else None

    transcript_data = store.persistence.load_json(task_id, "transcript.json")
    if not transcript_data:
        raise ValueError(f"task {task_id} has no transcript.json, cannot reaudit")

    # 与前端提交合规审核时同样的字段子集（见 api/compliance.ts 的 auditCompliance）
    entries = [
        {
            "timestamp": e.get("timestamp"),
            "timestamp_ms": e.get("timestamp_ms"),
            "speaker": e.get("speaker"),
            "text_corrected": e.get("text_corrected"),
        }
        for e in transcript_data.get("transcript", [])
    ]

    sub_task_id = store.submit_compliance_audit(
        transcript_entries=entries,
        rules_bytes=b"",
        rules_filename="",
        parent_task_id=task_id,
        use_rule_library=True,
    )
    await _wait_for_terminal(store, sub_task_id)

    sub_task = store.get(sub_task_id)
    if sub_task is not None and sub_task.status == TaskStatus.FAILED:
        raise RuntimeError(sub_task.error or "reaudit task failed")

    new_data = store.persistence.load_json(task_id, "compliance.json")
    new_score = new_data["report"]["compliance_score"] if new_data else None
    if old_score is not None and new_score is not None and old_score != new_score:
        job.diffs.append(ReauditDiff(task_id=task_id, old_score=old_score, new_score=new_score))


async def _wait_for_terminal(store: TaskStore, task_id: str) -> None:
    while True:
        task = store.get(task_id)
        if task is None or task.status in TERMINAL_STATUSES:
            return
        await asyncio.sleep(_POLL_INTERVAL_S)
