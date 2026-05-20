import asyncio
import contextlib
import logging
import time
import uuid

from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResponse
from copernicus.schemas.task import TaskProgress, TaskStatus
from copernicus.schemas.transcription import (
    TranscriptEntrySchema,
    TranscriptResponse,
)
from copernicus.config import Settings
from copernicus.exceptions import AudioNotFoundError, ServiceNotConfiguredError, TaskNotFoundError
from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.model_manager import ModelManager
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline import PipelineService
from copernicus.services.template_manager import TemplateManager

logger = logging.getLogger(__name__)

# Statuses where the LLM (Ollama) is actively occupying VRAM.
# Used by the synthesis router to reject concurrent TTS requests.
LLM_ACTIVE_STATUSES: frozenset[TaskStatus] = frozenset({
    TaskStatus.CORRECTING,
    TaskStatus.EVALUATING,
    TaskStatus.AUDITING,
})

TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
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


class TaskInfo:
    __slots__ = (
        "task_id",
        "status",
        "current_chunk",
        "total_chunks",
        "result",
        "error",
        "eval_only",
        "audio_path",
        "parent_task_id",
    )

    def __init__(
        self,
        task_id: str,
        *,
        eval_only: bool = False,
        parent_task_id: str | None = None,
    ) -> None:
        self.task_id = task_id
        self.status = TaskStatus.PENDING
        self.current_chunk = 0
        self.total_chunks = 0
        self.result: (
            EvaluationResponse
            | TranscriptResponse
            | ComplianceResponse
            | None
        ) = None
        self.error: str | None = None
        self.eval_only = eval_only
        self.audio_path: str | None = None
        self.parent_task_id = parent_task_id

    @property
    def progress(self) -> TaskProgress:
        if self.status == TaskStatus.PENDING:
            percent = 0.0
        elif self.status == TaskStatus.EXTRACTING_FRAMES:
            percent = 5.0
        elif self.status == TaskStatus.SCANNING_VISUAL:
            if self.total_chunks > 0:
                percent = 5.0 + (self.current_chunk / self.total_chunks) * 15.0
            else:
                percent = 10.0
        elif self.status == TaskStatus.PROCESSING_ASR:
            percent = 20.0
        elif self.status == TaskStatus.CORRECTING and self.total_chunks > 0:
            percent = 20.0 + (self.current_chunk / self.total_chunks) * 70.0
        elif self.status == TaskStatus.AUDITING:
            if self.total_chunks > 0:
                percent = (self.current_chunk / self.total_chunks) * 100.0
            else:
                percent = 0.0
        elif self.status == TaskStatus.EVALUATING:
            if self.eval_only:
                if self.total_chunks > 0:
                    percent = (self.current_chunk / self.total_chunks) * 100.0
                else:
                    percent = 0.0
            else:
                if self.total_chunks > 0:
                    percent = 90.0 + (self.current_chunk / self.total_chunks) * 10.0
                else:
                    percent = 90.0
        elif self.status == TaskStatus.COMPLETED:
            percent = 100.0
        else:
            percent = 20.0 + (self.current_chunk / max(self.total_chunks, 1)) * 70.0
        return TaskProgress(
            current_chunk=self.current_chunk,
            total_chunks=self.total_chunks,
            percent=round(percent, 1),
        )


class _SynthesisJob:
    __slots__ = ("status", "error", "duration_ms", "synthesis_time_ms")

    def __init__(self) -> None:
        self.status: str = "running"
        self.error: str | None = None
        self.duration_ms: float | None = None
        self.synthesis_time_ms: float | None = None


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
        self._synthesis_jobs: dict[str, _SynthesisJob] = {}
        self._template_manager = template_manager
        self._task_timeout = settings.task_timeout_seconds
        self._max_tasks = settings.task_max_in_memory
        self._tasks: dict[str, TaskInfo] = {}
        self._hash_index: dict[str, str] = persistence.load_hash_index()

    @property
    def persistence(self) -> PersistenceService:
        return self._persistence

    def get_active_llm_task_ids(self) -> list[str]:
        """返回当前正在占用 LLM/VRAM 的任务 ID 列表（用于合成前的冲突检测）。"""
        return [tid for tid, t in self._tasks.items() if t.status in LLM_ACTIVE_STATUSES]

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
        self._synthesis_jobs[task_id] = _SynthesisJob()
        return True

    def get_synthesis_job(self, task_id: str) -> _SynthesisJob | None:
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
        # Task still in memory (running / pending / failed)
        if task_id in self._tasks:
            return task_id
        # Task completed and persisted to disk
        if self._persistence.has_file(task_id, "transcript.json"):
            return task_id
        # Stale index entry: task evicted from memory without completing
        del self._hash_index[file_hash]
        self._persistence.save_hash_index(self._hash_index)
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
        stale_hashes = [h for h, tid in self._hash_index.items() if tid == task_id]
        for h in stale_hashes:
            del self._hash_index[h]
        if stale_hashes:
            self._persistence.save_hash_index(self._hash_index)
        return task is not None or bool(stale_hashes)

    # -- restore from disk ---------------------------------------------------

    def restore_from_disk(self) -> None:
        """扫描上传目录，将已完成任务恢复到内存中，并从 meta.json 重建 hash index。"""
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

            info = TaskInfo(task_id)
            info.audio_path = entry["audio_path"]

            if entry["has_transcript"]:
                try:
                    data = self._persistence.load_json(task_id, "transcript.json")
                    if data:
                        info.result = TranscriptResponse.model_validate(data)
                        info.status = TaskStatus.COMPLETED
                except Exception as e:
                    logger.warning("Skipping task %s during restore: %s", task_id, e)
                    continue

            if info.status != TaskStatus.COMPLETED:
                continue

            self._tasks[task_id] = info
            logger.info("Restored task %s from disk", task_id)

        if index_dirty:
            self._persistence.save_hash_index(self._hash_index)
            logger.info("Rebuilt hash index from meta.json files")

        logger.info("Total tasks in memory: %d", len(self._tasks))

    # -- submit methods ------------------------------------------------------

    def _register_task(self, task_id: str, **kwargs) -> TaskInfo:
        """创建 TaskInfo 并存储，必要时淘汰旧任务。"""
        info = TaskInfo(task_id, **kwargs)
        self._tasks[task_id] = info
        self._evict_completed()
        return info

    def submit_transcript(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
        *,
        file_hash: str = "",
        visual_scan: bool = False,
    ) -> str:
        task_id = uuid.uuid4().hex
        self._register_task(task_id)
        asyncio.create_task(
            self._run_with_timeout(
                task_id,
                self._run_transcript(task_id, audio_bytes, filename, hotwords, visual_scan=visual_scan),
            )
        )
        if file_hash:
            self._register_hash(file_hash, task_id)
        logger.info("Task %s submitted (transcript, visual_scan=%s)", task_id, visual_scan)
        return task_id

    def submit_standard_minutes(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
        *,
        file_hash: str = "",
        visual_scan: bool = False,
        generate_summary: bool = True,
        template_id: str = "universal",
    ) -> str:
        """提交标准纪要任务：Pipeline 完成后自动生成摘要。"""
        task_id = uuid.uuid4().hex
        self._register_task(task_id)
        asyncio.create_task(
            self._run_with_timeout(
                task_id,
                self._run_standard_minutes(
                    task_id, audio_bytes, filename, hotwords,
                    visual_scan=visual_scan,
                    generate_summary=generate_summary,
                    template_id=template_id,
                ),
            )
        )
        if file_hash:
            self._register_hash(file_hash, task_id)
        logger.info(
            "Task %s submitted (standard_minutes, visual_scan=%s, summary=%s, template=%s)",
            task_id, visual_scan, generate_summary, template_id,
        )
        return task_id

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
        task_id = uuid.uuid4().hex
        self._register_task(task_id, eval_only=True, parent_task_id=parent_task_id)
        asyncio.create_task(
            self._run_with_timeout(
                task_id, self._run_text_evaluation(task_id, text, template_id)
            )
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
        task_id = uuid.uuid4().hex
        self._register_task(task_id, eval_only=True, parent_task_id=parent_task_id)
        asyncio.create_task(
            self._run_with_timeout(
                task_id,
                self._run_compliance_audit(
                    task_id, transcript_entries, rules_bytes, rules_filename
                ),
            )
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
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")

        audio_path = self._persistence.find_audio(task_id)
        if audio_path is None:
            raise AudioNotFoundError(f"Audio not found for task {task_id}")

        audio_bytes = audio_path.read_bytes()
        suffix = audio_path.suffix

        # reset task state
        task.status = TaskStatus.PENDING
        task.current_chunk = 0
        task.total_chunks = 0
        task.result = None
        task.error = None

        # invalidate downstream results
        self._persistence.delete_file(task_id, "evaluation.json")
        self._persistence.delete_file(task_id, "compliance.json")

        asyncio.create_task(
            self._run_with_timeout(
                task_id,
                self._run_transcript(task_id, audio_bytes, f"audio{suffix}", hotwords),
            )
        )
        logger.info("Task %s rerun (transcript)", task_id)
        return task_id

    def rerun_evaluation(self, parent_task_id: str, template_id: str = "universal") -> str:
        """基于已有转写结果重新执行评估，返回子任务 task_id。"""
        data = self._persistence.load_json(parent_task_id, "transcript.json")
        if data is None:
            raise AudioNotFoundError(f"transcript.json not found for task {parent_task_id}")

        transcript = TranscriptResponse.model_validate(data)
        full_text = "\n".join(e.text_corrected for e in transcript.transcript)
        if not full_text.strip():
            raise ValueError("Transcript text is empty")

        self._persistence.delete_file(parent_task_id, "evaluation.json")
        return self.submit_text_evaluation(
            full_text, template_id=template_id, parent_task_id=parent_task_id
        )

    # -- get -----------------------------------------------------------------

    def get(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

    # -- memory management ---------------------------------------------------

    def _evict_completed(self) -> None:
        """内存超限时淘汰最早完成/失败的任务。"""
        if len(self._tasks) <= self._max_tasks:
            return
        terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED)
        evict_ids = [
            tid
            for tid, t in self._tasks.items()
            if t.status in terminal
        ]
        # Evict from the front (oldest inserted first, dict preserves insertion order)
        to_remove = len(self._tasks) - self._max_tasks
        for tid in evict_ids[:to_remove]:
            del self._tasks[tid]
        if to_remove > 0:
            logger.info("Evicted %d completed tasks (total: %d)", min(to_remove, len(evict_ids)), len(self._tasks))

    # -- timeout wrapper -----------------------------------------------------

    async def _run_with_timeout(self, task_id: str, coro) -> None:
        """为任务协程添加超时保护。"""
        try:
            await asyncio.wait_for(coro, timeout=self._task_timeout)
        except asyncio.TimeoutError:
            task = self._tasks.get(task_id)
            if task and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                task.status = TaskStatus.FAILED
                task.error = f"任务超时（{self._task_timeout}s）"
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
            task.status = TaskStatus.FAILED
            task.error = str(e) or type(e).__name__
            logger.error(
                "Task %s failed: [%s] %s", task_id, type(e).__name__, e, exc_info=True
            )

    async def _run_text_evaluation(
        self, task_id: str, text: str, template_id: str
    ) -> None:
        async with self._task_lifecycle(task_id, "text evaluation") as task:
            task.status = TaskStatus.EVALUATING
            task.current_chunk = 0
            task.total_chunks = 0
            if self._evaluator is None:
                raise RuntimeError("EvaluatorService not configured")

            template_prompt = (
                self._template_manager.get_prompt(template_id)
                if self._template_manager
                else "你是一个会议助手，请根据以下转写文本生成会议纪要。"
            )

            def on_eval_progress(current: int, total: int) -> None:
                task.current_chunk = current
                task.total_chunks = total

            evaluation = await self._evaluator.evaluate(
                text, template_prompt, on_progress=on_eval_progress
            )

            task.result = EvaluationResponse(
                raw_text="",
                corrected_text=text,
                evaluation=evaluation,
                processing_time_ms=0,
            )

            if task.parent_task_id:
                self._persistence.save_json(
                    task.parent_task_id, "evaluation.json", evaluation
                )

    async def _execute_pipeline(
        self,
        task: TaskInfo,
        audio_bytes: bytes,
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
                task.status = TaskStatus(new_status)
                task.current_chunk = 0
                task.total_chunks = 0

        def on_progress(current: int, total: int) -> None:
            task.current_chunk = current
            task.total_chunks = total

        if self._model_manager:
            await self._model_manager.ensure("asr")

        result = await self._pipeline.process_transcript(
            audio_bytes, filename, hotwords,
            on_progress=on_progress,
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
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None,
        *,
        visual_scan: bool = False,
    ) -> None:
        async with self._task_lifecycle(task_id, "transcript") as task:
            await self._execute_pipeline(task, audio_bytes, filename, hotwords, visual_scan, task_id)

    async def _run_standard_minutes(
        self,
        task_id: str,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None,
        *,
        visual_scan: bool = False,
        generate_summary: bool = True,
        template_id: str = "universal",
    ) -> None:
        async with self._task_lifecycle(task_id, "standard_minutes") as task:
            transcript_response = await self._execute_pipeline(
                task, audio_bytes, filename, hotwords, visual_scan, task_id
            )

            if generate_summary and self._evaluator:
                task.status = TaskStatus.EVALUATING
                task.current_chunk = 0
                task.total_chunks = 0

                full_text = "\n".join(e.text_corrected for e in transcript_response.transcript)
                if full_text.strip():
                    template_prompt = (
                        self._template_manager.get_prompt(template_id)
                        if self._template_manager
                        else "你是一个会议助手，请根据以下转写文本生成会议纪要。"
                    )

                    def on_eval_progress(current: int, total: int) -> None:
                        task.current_chunk = current
                        task.total_chunks = total

                    evaluation = await self._evaluator.evaluate(
                        full_text, template_prompt, on_progress=on_eval_progress
                    )
                    self._persistence.save_json(task_id, "evaluation.json", evaluation)
                    logger.info(
                        "Task %s: summary generated (standard_minutes, template=%s)",
                        task_id, template_id,
                    )

    async def _run_compliance_audit(
        self,
        task_id: str,
        transcript_entries: list[dict],
        rules_bytes: bytes,
        rules_filename: str,
    ) -> None:
        async with self._task_lifecycle(task_id, "compliance audit") as task:
            task.status = TaskStatus.AUDITING
            task.current_chunk = 0
            task.total_chunks = 0
            if self._compliance is None:
                raise RuntimeError("ComplianceService not configured")

            start = time.perf_counter()
            rules, few_shot_examples = self._compliance.parse_rules(
                rules_bytes, rules_filename
            )

            # 卸载 ASR 以释放 VRAM 供 14B LLM 推理使用
            if self._model_manager:
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

            def on_audit_progress(current: int, total: int) -> None:
                task.current_chunk = current
                task.total_chunks = total

            report = await self._compliance.audit(
                rules,
                transcript_entries,
                few_shot_examples=few_shot_examples,
                on_progress=on_audit_progress,
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
