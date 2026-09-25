import asyncio
import contextlib
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResponse, EvaluationResult
from copernicus.schemas.task import TaskStatus, TaskSummary
from copernicus.schemas.transcription import (
    TranscriptEntrySchema,
    TranscriptResponse,
)
from copernicus.config import Settings
from copernicus.exceptions import (
    AudioNotFoundError,
    InvalidIdentifierError,
    QueueFullError,
    ServiceNotConfiguredError,
    TaskBusyError,
    TaskNotFoundError,
)
from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.model_manager import ModelManager
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_state import (
    LLM_ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    SynthesisJob,
    TaskInfo,
)
from copernicus.services.template_manager import FALLBACK_PROMPT, TemplateManager
from copernicus.services.transcript_edit import apply_speaker_renames, apply_text_edits

logger = logging.getLogger(__name__)

# 服务重启时仍无结果的任务：进程内状态已丢失，只能标记为失败
_INTERRUPTED_MESSAGE = "服务重启导致任务中断，请重新转写或重新上传"
_CANCELLED_MESSAGE = "任务已取消"

# 仅这些阶段可安全取消：其余阶段（ASR、视觉扫描）运行在线程中，无法中断，
# 取消协程会让线程继续占用 GPU，同时放行下一个任务，造成显存冲突
_CANCELLABLE_STATUSES: frozenset[TaskStatus] = frozenset({
    TaskStatus.PENDING,
    TaskStatus.CORRECTING,
    TaskStatus.EVALUATING,
    TaskStatus.AUDITING,
})

_PIPELINE_STAGE_STATUS: dict[str, "TaskStatus"] = {
    "video_preprocess": "extracting_frames",
    "keyframe_extract": "extracting_frames",
    "ocr_scan": "scanning_visual",
    "face_detect": "scanning_visual",
    "audio_preprocess": "processing_asr",
    "asr_transcribe": "processing_asr",
    "text_correction": "correcting",
}


class TaskStore:
    def __init__(
        self,
        pipeline: PipelineService,
        persistence: PersistenceService,
        settings: Settings,
        evaluator: EvaluatorService | None = None,
        compliance: ComplianceService | None = None,
        model_manager: ModelManager | None = None,
        template_manager: TemplateManager | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._evaluator = evaluator
        self._compliance = compliance
        self._persistence = persistence
        self._model_manager = model_manager
        self._llm_is_local = settings.llm_provider == "ollama"
        self._synthesis_jobs: dict[str, SynthesisJob] = {}
        self._template_manager = template_manager
        self._task_timeout = settings.task_timeout_seconds
        self._max_tasks = settings.task_max_in_memory
        self._max_active = settings.task_max_active
        self._video_extensions = settings.video_extensions_set
        self._handles: dict[str, asyncio.Task] = {}
        self._tasks: dict[str, TaskInfo] = {}
        self._invalidated: set[str] = set()  # 已被用户作废，不再从磁盘惰性恢复
        self._hash_index: dict[str, str] = persistence.load_hash_index()

    @property
    def persistence(self) -> PersistenceService:
        return self._persistence

    def has_active_llm_tasks(self) -> bool:
        """是否有任务正在占用 LLM/VRAM（用于合成前的冲突检测）。"""
        return any(t.status in LLM_ACTIVE_STATUSES for t in self._tasks.values())

    def get_task_stats(self) -> dict[str, int]:
        """返回任务队列统计：active / completed / failed / synthesis_running。"""
        tasks = list(self._tasks.values())
        return {
            "active": sum(1 for t in tasks if t.status not in TERMINAL_STATUSES),
            "completed": sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in tasks if t.status == TaskStatus.FAILED),
            "synthesis_running": sum(
                1 for j in self._synthesis_jobs.values() if j.status == "running"
            ),
        }

    # -- synthesis job tracking --------------------------------------------------

    def start_synthesis(self, task_id: str) -> bool:
        """标记合成任务开始；若该 task 已有合成在运行则返回 False。"""
        job = self._synthesis_jobs.get(task_id)
        if job is not None and job.status == "running":
            return False
        self._synthesis_jobs[task_id] = SynthesisJob()
        return True

    def get_synthesis_job(self, task_id: str) -> SynthesisJob | None:
        return self._synthesis_jobs.get(task_id)

    def finish_synthesis(self, task_id: str, duration_ms: float, synthesis_time_ms: float) -> None:
        job = self._synthesis_jobs.get(task_id)
        if job:
            job.status = "completed"
            job.duration_ms = duration_ms
            job.synthesis_time_ms = synthesis_time_ms

    def fail_synthesis(self, task_id: str, error: str) -> None:
        job = self._synthesis_jobs.get(task_id)
        if job:
            job.status = "failed"
            job.error = error

    # -- hash dedup ----------------------------------------------------------

    def lookup_by_hash(self, file_hash: str) -> str | None:
        """根据文件哈希查找已有 task_id，不存在则返回 None。"""
        task_id = self._hash_index.get(file_hash)
        if task_id is None:
            return None
        # Task still in memory (running / pending)；失败任务不复用，允许同一文件重新提交
        task = self._tasks.get(task_id)
        if task is not None:
            if task.status == TaskStatus.FAILED:
                del self._hash_index[file_hash]
                return None
            return task_id
        # Task completed and persisted to disk
        if self._persistence.has_file(task_id, "transcript.json"):
            return task_id
        # Stale index entry: remove from memory; persisted on next write or restart
        del self._hash_index[file_hash]
        return None

    def _register_hash(self, file_hash: str, task_id: str) -> None:
        self._hash_index[file_hash] = task_id
        self._persistence.save_hash_index(self._hash_index)

    def invalidate_task(self, task_id: str) -> bool:
        """从内存和哈希索引中移除任务，使同一文件可以重新提交处理。

        不删除磁盘上的任何文件，仅清除缓存状态。
        返回 True 表示任务存在并已清除，False 表示任务不在内存中。
        """
        task = self._tasks.pop(task_id, None)
        self._invalidated.add(task_id)
        stale_hashes = [h for h, tid in self._hash_index.items() if tid == task_id]
        for h in stale_hashes:
            del self._hash_index[h]
        if stale_hashes:
            self._persistence.save_hash_index(self._hash_index)
        return task is not None or bool(stale_hashes)

    # -- restore from disk ---------------------------------------------------

    def restore_from_disk(self) -> None:
        """扫描上传目录，恢复任务到内存，并从 meta.json 重建 hash index。

        有转写结果的恢复为 COMPLETED；仍保留媒体但无结果的（失败或被重启打断）恢复为 FAILED，
        使前端轮询得到明确状态而非 404，并可通过重新转写恢复。
        """
        index_dirty = False
        for entry in self._persistence.scan_completed_tasks():
            task_id = entry["task_id"]

            # 从 meta.json 重建 hash index（兼容 hash_index.json 丢失/损坏的场景）
            file_hash = entry.get("meta", {}).get("hash")
            if file_hash and file_hash not in self._hash_index:
                self._hash_index[file_hash] = task_id
                index_dirty = True

            if task_id in self._tasks:
                continue
            info = self._build_task_from_disk(entry)
            if info is None:
                continue
            self._tasks[task_id] = info
            logger.info("Restored task %s from disk (%s)", task_id, info.status.value)

        # 清理 hash_index 中指向不存在任务的 stale 条目
        stale = [
            h for h, tid in self._hash_index.items()
            if tid not in self._tasks
            and not self._persistence.has_file(tid, "transcript.json")
        ]
        for h in stale:
            del self._hash_index[h]
        if stale:
            index_dirty = True
            logger.info("Removed %d stale hash index entries", len(stale))

        if index_dirty:
            self._persistence.save_hash_index(self._hash_index)
            logger.info("Rebuilt hash index from meta.json files")

        logger.info("Total tasks in memory: %d", len(self._tasks))

    @staticmethod
    def _disk_status(entry: dict) -> TaskStatus | None:
        """由磁盘内容推断任务状态：有转写为 COMPLETED，仅剩媒体为 FAILED，其余不可恢复。"""
        if entry["has_transcript"]:
            return TaskStatus.COMPLETED
        if entry["audio_path"] or entry["has_video"]:
            return TaskStatus.FAILED
        return None

    def _build_task_from_disk(self, entry: dict) -> TaskInfo | None:
        """依据磁盘扫描条目重建 TaskInfo；无可恢复内容时返回 None。"""
        status = self._disk_status(entry)
        if status is None:
            return None

        task_id = entry["task_id"]
        info = TaskInfo(task_id)
        info.audio_path = entry["audio_path"]
        info.status = status

        if status == TaskStatus.COMPLETED:
            try:
                data = self._persistence.load_json(task_id, "transcript.json")
                if not data:
                    return None
                info.result = TranscriptResponse.model_validate(data)
            except Exception as e:
                logger.warning("Skipping task %s during restore: %s", task_id, e)
                return None
        else:
            info.error = self._failure_error(task_id)
        return info

    def _failure_error(self, task_id: str) -> str:
        return self._persistence.load_failure_error(task_id) or _INTERRUPTED_MESSAGE

    # -- task management (history / rename / purge / transcript proofreading) --

    def list_tasks(self, limit: int = 100) -> tuple[list[TaskSummary], int]:
        """按创建时间倒序返回历史任务摘要，以及磁盘上的任务总数。"""
        entries = [
            e for e in self._persistence.scan_completed_tasks()
            if e["task_id"] not in self._invalidated
        ]
        entries.sort(key=lambda e: e["meta"].get("created_at", ""), reverse=True)

        summaries: list[TaskSummary] = []
        for entry in entries[:limit]:
            task_id = entry["task_id"]
            live = self._tasks.get(task_id)
            status = live.status if live else self._disk_status(entry)
            if status is None:
                continue
            if live:
                error = live.error
            else:
                error = self._failure_error(task_id) if status == TaskStatus.FAILED else None
            meta = entry["meta"]
            filename = meta.get("filename", "")
            summaries.append(
                TaskSummary(
                    task_id=task_id,
                    name=meta.get("display_name")
                    or self._evaluation_title(task_id, entry)
                    or filename,
                    filename=filename,
                    created_at=meta.get("created_at", ""),
                    status=status,
                    error=error,
                    has_video=entry["has_video"],
                    has_evaluation=entry["has_evaluation"],
                    has_compliance=entry["has_compliance"],
                )
            )
        return summaries, len(entries)

    def _evaluation_title(self, task_id: str, entry: dict) -> str:
        if not entry["has_evaluation"]:
            return ""
        data = self._persistence.load_json(task_id, "evaluation.json")
        return (data or {}).get("title", "")

    def rename_task(self, task_id: str, name: str) -> None:
        if not self._persistence.update_meta(task_id, display_name=name):
            raise TaskNotFoundError(f"Task {task_id} not found")

    def purge_task(self, task_id: str) -> bool:
        """彻底删除任务：内存状态、哈希索引与磁盘上的全部文件。运行中的任务不允许删除。"""
        task = self.get(task_id)
        job = self._synthesis_jobs.get(task_id)
        if (task and task.status not in TERMINAL_STATUSES) or (job and job.status == "running"):
            raise TaskBusyError(f"Task {task_id} is still running")
        invalidated = self.invalidate_task(task_id)
        deleted = self._persistence.delete_task(task_id)
        self._synthesis_jobs.pop(task_id, None)
        return invalidated or deleted

    def edit_transcript(self, task_id: str, edits: dict[int, str]) -> int:
        """人工修订句段文本并回写，返回实际变更条数。"""
        return self._update_transcript(task_id, lambda t: apply_text_edits(t, edits))

    def rename_speakers(self, task_id: str, renames: dict[str, str]) -> int:
        """重命名/合并说话人并回写，返回受影响句段数。"""
        return self._update_transcript(task_id, lambda t: apply_speaker_renames(t, renames))

    def _update_transcript(self, task_id: str, transform) -> int:
        task = self.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")
        if task.status != TaskStatus.COMPLETED:
            raise TaskBusyError(f"Task {task_id} is not completed")
        data = self._persistence.load_json(task_id, "transcript.json")
        if data is None:
            raise TaskNotFoundError(f"transcript.json not found for task {task_id}")

        updated, changed = transform(TranscriptResponse.model_validate(data))
        if changed:
            self._persistence.save_json(task_id, "transcript.json", updated)
            task.result = updated
        return changed

    # -- submit methods ------------------------------------------------------

    def _register_task(self, task_id: str, **kwargs) -> TaskInfo:
        """创建 TaskInfo 并存储，必要时淘汰旧任务。"""
        info = TaskInfo(task_id, **kwargs)
        self._tasks[task_id] = info
        self._evict_completed()
        return info

    async def _submit_media_task(
        self, source: Path, filename: str, file_hash: str, label: str, make_run
    ) -> str:
        """音视频任务的公共提交流程：占位 → 媒体落盘 → 启动。

        媒体必须先落盘再启动管线：管线第一个阶段就会读取任务目录里的文件，
        先启动会让它读到写了一半的大文件。
        """
        self.ensure_capacity()
        task_id = uuid.uuid4().hex
        info = self._register_task(task_id)
        if file_hash:
            # 占位即登记：落盘期间到达的同一文件的重复上传会命中本任务，而不是再开一个
            self._register_hash(file_hash, task_id)
        try:
            media_path = await asyncio.to_thread(
                self._persistence.adopt_media,
                task_id, filename, file_hash, source, self._video_extensions,
            )
        except BaseException:  # 含客户端断开导致的取消：不能留下无媒体的幽灵任务
            self._discard_submission(task_id, file_hash)
            raise
        info.audio_path = str(media_path)
        self._spawn(task_id, make_run(task_id, media_path))
        logger.info("Task %s submitted (%s)", task_id, label)
        return task_id

    def _discard_submission(self, task_id: str, file_hash: str) -> None:
        self._tasks.pop(task_id, None)
        if file_hash and self._hash_index.get(file_hash) == task_id:
            del self._hash_index[file_hash]
            self._persistence.save_hash_index(self._hash_index)
        self._persistence.delete_task(task_id)

    async def submit_transcript(
        self,
        source: Path,
        filename: str,
        hotwords: list[str] | None = None,
        *,
        file_hash: str = "",
        visual_scan: bool = False,
    ) -> str:
        """提交转写任务。source 是已落盘的上传文件，会被移入任务目录。"""
        return await self._submit_media_task(
            source, filename, file_hash, f"transcript, visual_scan={visual_scan}",
            lambda task_id, media: self._run_transcript(
                task_id, media, filename, hotwords, visual_scan=visual_scan
            ),
        )

    async def submit_standard_minutes(
        self,
        source: Path,
        filename: str,
        hotwords: list[str] | None = None,
        *,
        file_hash: str = "",
        visual_scan: bool = False,
        generate_summary: bool = True,
        template_id: str = "universal",
    ) -> str:
        """提交标准纪要任务：Pipeline 完成后自动生成摘要。source 是已落盘的上传文件。"""
        return await self._submit_media_task(
            source, filename, file_hash,
            f"standard_minutes, visual_scan={visual_scan}, summary={generate_summary}, template={template_id}",
            lambda task_id, media: self._run_standard_minutes(
                task_id, media, filename, hotwords,
                visual_scan=visual_scan,
                generate_summary=generate_summary,
                template_id=template_id,
            ),
        )

    def _require_parent(self, parent_task_id: str | None) -> None:
        """关联的父任务必须存在。否则结果只会在算完 LLM 后才因目录不存在而落盘失败，白白浪费算力。"""
        if parent_task_id is not None and not self._persistence.has_file(parent_task_id, "meta.json"):
            raise TaskNotFoundError(f"Parent task {parent_task_id} not found")

    def submit_text_evaluation(
        self,
        text: str,
        *,
        template_id: str = "universal",
        parent_task_id: str | None = None,
    ) -> str:
        """提交纯文本评估任务（不需要 ASR）。"""
        if self._evaluator is None:
            raise ServiceNotConfiguredError("EvaluatorService not configured")
        self._require_parent(parent_task_id)
        task_id = uuid.uuid4().hex
        self._register_task(task_id, eval_only=True, parent_task_id=parent_task_id)
        self._spawn(
            task_id,
            self._run_text_evaluation(task_id, text, template_id),
        )
        logger.info(
            "Task %s submitted (text evaluation, template=%s, parent=%s)",
            task_id, template_id, parent_task_id,
        )
        return task_id

    def submit_compliance_audit(
        self,
        transcript_entries: list[dict],
        rules_bytes: bytes,
        rules_filename: str,
        *,
        parent_task_id: str | None = None,
    ) -> str:
        """提交合规审核任务（纯文本，不需要 ASR）。"""
        if self._compliance is None:
            raise ServiceNotConfiguredError("ComplianceService not configured")
        self._require_parent(parent_task_id)
        task_id = uuid.uuid4().hex
        self._register_task(task_id, eval_only=True, parent_task_id=parent_task_id)
        self._spawn(
            task_id,
            self._run_compliance_audit(
                task_id, transcript_entries, rules_bytes, rules_filename
            ),
        )
        logger.info("Task %s submitted (compliance audit, parent=%s)", task_id, parent_task_id)
        return task_id

    # -- rerun methods -------------------------------------------------------

    def rerun_transcript(
        self,
        task_id: str,
        hotwords: list[str] | None = None,
    ) -> str:
        """对已有音频重新执行 ASR 和纠正，返回相同的 task_id。"""
        task = self.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")
        if task.status not in TERMINAL_STATUSES:
            raise TaskBusyError(f"Task {task_id} is still running")
        self.ensure_capacity()

        media_path = self._persistence.find_video(task_id) or self._persistence.find_audio(task_id)
        if media_path is None:
            raise AudioNotFoundError(f"Audio not found for task {task_id}")

        # reset task state
        task.enter(TaskStatus.PENDING)
        task.result = None
        task.error = None

        # invalidate all prior results
        self._persistence.clear_failure(task_id)
        # 标记重新处理时间，避免生命周期清理把处理中的旧任务当作过期任务
        self._persistence.update_meta(task_id, processed_at=datetime.now(timezone.utc).isoformat())
        self._persistence.delete_file(task_id, "transcript.json")
        self._persistence.delete_file(task_id, "evaluation.json")
        self._persistence.delete_file(task_id, "compliance.json")

        self._spawn(
            task_id,
            # 文件名用落盘文件自己的名字：管线靠后缀判断是否为视频
            self._run_transcript(task_id, media_path, media_path.name, hotwords),
        )
        logger.info("Task %s rerun (transcript)", task_id)
        return task_id

    # -- get -----------------------------------------------------------------

    def get(self, task_id: str) -> TaskInfo | None:
        """获取任务；内存中不存在时（如已被淘汰）尝试从磁盘惰性恢复。"""
        task = self._tasks.get(task_id)
        if task is not None or task_id in self._invalidated:
            return task
        try:
            entry = self._persistence.scan_task(task_id)
        except InvalidIdentifierError:
            return None
        if entry is None:
            return None
        task = self._build_task_from_disk(entry)
        if task is not None:
            self._tasks[task_id] = task
        return task

    # -- memory management ---------------------------------------------------

    def _evict_completed(self) -> None:
        """内存超限时淘汰最早完成/失败的任务。"""
        if len(self._tasks) <= self._max_tasks:
            return
        evict_ids = [tid for tid, t in self._tasks.items() if t.status in TERMINAL_STATUSES]
        # Evict from the front (oldest inserted first, dict preserves insertion order)
        to_remove = len(self._tasks) - self._max_tasks
        for tid in evict_ids[:to_remove]:
            del self._tasks[tid]
            self._synthesis_jobs.pop(tid, None)
        if to_remove > 0:
            logger.info("Evicted %d completed tasks (total: %d)", min(to_remove, len(evict_ids)), len(self._tasks))

    def _mark_failed(self, task: TaskInfo, error: str) -> None:
        """置任务为失败并落盘失败原因，使服务重启后仍能恢复该状态。"""
        task.status = TaskStatus.FAILED
        task.error = error
        try:
            self._persistence.save_failure(task.task_id, error)
        except Exception:
            logger.warning("Failed to persist failure of task %s", task.task_id, exc_info=True)

    # -- scheduling ----------------------------------------------------------

    def ensure_capacity(self) -> None:
        """音视频任务排队+运行数已达上限时抛出 QueueFullError（调用方应返回 429）。"""
        if self._max_active <= 0:
            return
        active = sum(
            1 for t in self._tasks.values()
            if not t.eval_only and t.status not in TERMINAL_STATUSES
        )
        if active >= self._max_active:
            raise QueueFullError(f"任务队列已满（{active}/{self._max_active}），请稍后重试")

    def _spawn(self, task_id: str, coro) -> None:
        """在后台运行任务协程（带超时保护），并保存句柄以支持取消。"""
        handle = asyncio.create_task(self._run_with_timeout(task_id, coro))
        self._handles[task_id] = handle

        def _forget(done: asyncio.Task) -> None:
            # 重跑会为同一 task_id 换上新句柄，只清理属于自己的
            if self._handles.get(task_id) is done:
                del self._handles[task_id]

        handle.add_done_callback(_forget)

    def cancel_task(self, task_id: str) -> None:
        """取消排队中或处于 LLM 阶段的任务；ASR 等不可中断的阶段返回 409。"""
        task = self.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")
        handle = self._handles.get(task_id)
        if handle is None or task.status in TERMINAL_STATUSES:
            raise TaskBusyError(f"Task {task_id} is not running")
        if task.status not in _CANCELLABLE_STATUSES:
            raise TaskBusyError(
                f"当前阶段（{task.status.value}）无法中断，请等待该阶段完成后再取消"
            )
        handle.cancel()

    async def cancel_all(self) -> None:
        """服务关停时取消全部后台任务并等待其退出。"""
        handles = list(self._handles.values())
        for handle in handles:
            handle.cancel()
        await asyncio.gather(*handles, return_exceptions=True)

    # -- timeout wrapper -----------------------------------------------------

    async def _run_with_timeout(self, task_id: str, coro) -> None:
        """为任务协程添加超时保护。"""
        try:
            await asyncio.wait_for(coro, timeout=self._task_timeout)
        except asyncio.CancelledError:
            task = self._tasks.get(task_id)
            if task and task.status not in TERMINAL_STATUSES:
                self._mark_failed(task, _CANCELLED_MESSAGE)
            raise
        except asyncio.TimeoutError:
            task = self._tasks.get(task_id)
            if task and task.status not in TERMINAL_STATUSES:
                self._mark_failed(task, f"任务超时（{self._task_timeout}s）")
                logger.error("Task %s timed out after %ds", task_id, self._task_timeout)

    # -- run implementations -------------------------------------------------

    @contextlib.asynccontextmanager
    async def _task_lifecycle(self, task_id: str, label: str):
        """所有 _run_* 方法通用的 try/except + 状态/错误/日志处理。"""
        task = self._tasks[task_id]
        try:
            yield task
            task.status = TaskStatus.COMPLETED
            logger.info("Task %s completed (%s)", task_id, label)
        except Exception as e:
            self._mark_failed(task, str(e) or type(e).__name__)
            logger.error(
                "Task %s failed: [%s] %s", task_id, type(e).__name__, e, exc_info=True
            )

    def _template_prompt(self, template_id: str) -> str:
        if self._template_manager is None:
            return FALLBACK_PROMPT
        return self._template_manager.get_prompt(template_id)

    async def _evaluate_text(self, task: TaskInfo, text: str, template_id: str) -> EvaluationResult:
        """摘要评估：纯文本评估任务与标准纪要的摘要阶段共用。"""
        if self._evaluator is None:
            raise RuntimeError("EvaluatorService not configured")
        task.enter(TaskStatus.EVALUATING)
        return await self._evaluator.evaluate(
            text, self._template_prompt(template_id), on_progress=task.set_progress
        )

    async def _run_text_evaluation(
        self, task_id: str, text: str, template_id: str
    ) -> None:
        async with self._task_lifecycle(task_id, "text evaluation") as task:
            evaluation = await self._evaluate_text(task, text, template_id)
            task.result = EvaluationResponse(
                raw_text="",
                corrected_text=text,
                evaluation=evaluation,
                processing_time_ms=0,
            )
            if task.parent_task_id:
                self._persistence.save_json(task.parent_task_id, "evaluation.json", evaluation)

    async def _execute_pipeline(
        self,
        task: TaskInfo,
        media_path: Path,
        filename: str,
        hotwords: list[str] | None,
        visual_scan: bool,
        task_id: str,
    ) -> TranscriptResponse:
        """执行 Pipeline 并返回 TranscriptResponse，同时保存 transcript.json。"""
        task.status = TaskStatus.PROCESSING_ASR

        def on_stage_change(stage_name: str) -> None:
            new_status = _PIPELINE_STAGE_STATUS.get(stage_name)
            if new_status:
                task.enter(TaskStatus(new_status))

        result = await self._pipeline.process_transcript(
            media_path, filename, hotwords,
            on_progress=task.set_progress,
            on_stage_change=on_stage_change,
            task_id=task_id,
            visual_scan=visual_scan,
        )

        transcript_response = TranscriptResponse(
            transcript=[
                TranscriptEntrySchema(
                    timestamp=entry.timestamp,
                    timestamp_ms=entry.timestamp_ms,
                    end_ms=entry.end_ms,
                    speaker=entry.speaker,
                    text=entry.text,
                    text_corrected=entry.text_corrected,
                )
                for entry in result.transcript
            ],
            processing_time_ms=result.processing_time_ms,
        )
        task.result = transcript_response
        self._persistence.save_json(task_id, "transcript.json", transcript_response)
        return transcript_response

    async def _run_transcript(
        self,
        task_id: str,
        media_path: Path,
        filename: str,
        hotwords: list[str] | None,
        *,
        visual_scan: bool = False,
    ) -> None:
        async with self._task_lifecycle(task_id, "transcript") as task:
            await self._execute_pipeline(task, media_path, filename, hotwords, visual_scan, task_id)

    async def _run_standard_minutes(
        self,
        task_id: str,
        media_path: Path,
        filename: str,
        hotwords: list[str] | None,
        *,
        visual_scan: bool = False,
        generate_summary: bool = True,
        template_id: str = "universal",
    ) -> None:
        async with self._task_lifecycle(task_id, "standard_minutes") as task:
            transcript_response = await self._execute_pipeline(
                task, media_path, filename, hotwords, visual_scan, task_id
            )
            if generate_summary and self._evaluator:
                await self._generate_summary(task, transcript_response, template_id)

    async def _generate_summary(
        self, task: TaskInfo, transcript: TranscriptResponse, template_id: str
    ) -> None:
        """标准纪要的摘要阶段。转写已落盘，摘要失败不应让整个任务变成失败：

        否则内存里是 FAILED（同一文件重传要重跑 ASR），重启后又因 transcript.json 存在而恢复为 COMPLETED，
        前后状态不一致。这里只记录警告；前端发现没有摘要时会自动重新生成。
        """
        full_text = "\n".join(e.text_corrected for e in transcript.transcript)
        if not full_text.strip():
            return
        try:
            evaluation = await self._evaluate_text(task, full_text, template_id)
        except Exception as e:
            logger.warning("Task %s: summary failed, transcript kept: %s", task.task_id, e, exc_info=True)
            return
        self._persistence.save_json(task.task_id, "evaluation.json", evaluation)
        logger.info("Task %s: summary generated (template=%s)", task.task_id, template_id)

    async def _run_compliance_audit(
        self,
        task_id: str,
        transcript_entries: list[dict],
        rules_bytes: bytes,
        rules_filename: str,
    ) -> None:
        async with self._task_lifecycle(task_id, "compliance audit") as task:
            task.enter(TaskStatus.AUDITING)
            if self._compliance is None:
                raise RuntimeError("ComplianceService not configured")

            start = time.perf_counter()
            rules, few_shot_examples = self._compliance.parse_rules(
                rules_bytes, rules_filename
            )

            # 本地 LLM（Ollama）与 ASR 争用显存：先卸载 ASR。远端 LLM 不占本机显存，
            # 此时卸载只会让下一个转写任务白白重载数十秒
            if self._model_manager and self._llm_is_local:
                await self._model_manager.unload("asr")

            # 从持久化层加载 OCR 数据（如果存在）
            ocr_results: list[dict] | None = None
            visual_events: list[dict] | None = None
            source_task_id = task.parent_task_id or task_id
            ocr_data = self._persistence.load_json(source_task_id, "ocr_results.json")
            if ocr_data and isinstance(ocr_data, list):
                ocr_results = ocr_data
                logger.info(
                    "Loaded %d OCR records for compliance audit (task=%s)",
                    len(ocr_results),
                    source_task_id,
                )
            ve_data = self._persistence.load_json(source_task_id, "visual_events.json")
            if ve_data and isinstance(ve_data, list):
                visual_events = ve_data

            report = await self._compliance.audit(
                rules,
                transcript_entries,
                few_shot_examples=few_shot_examples,
                on_progress=task.set_progress,
                ocr_results=ocr_results,
                visual_events=visual_events,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            compliance_response = ComplianceResponse(
                rules=rules,
                report=report,
                processing_time_ms=elapsed_ms,
            )
            task.result = compliance_response

            if task.parent_task_id:
                self._persistence.save_json(
                    task.parent_task_id, "compliance.json", compliance_response
                )
