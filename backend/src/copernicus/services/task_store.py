import asyncio
import logging
import uuid

from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResponse
from copernicus.schemas.task import TaskProgress, TaskStatus
from copernicus.schemas.transcription import (
    SegmentSchema,
    TranscriptionResponse,
    TranscriptEntrySchema,
    TranscriptResponse,
)
from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline import PipelineService

logger = logging.getLogger(__name__)


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
            TranscriptionResponse
            | EvaluationResponse
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
        elif self.status == TaskStatus.PROCESSING_ASR:
            percent = 5.0
        elif self.status == TaskStatus.CORRECTING and self.total_chunks > 0:
            percent = 5.0 + (self.current_chunk / self.total_chunks) * 85.0
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
            percent = 5.0 + (self.current_chunk / max(self.total_chunks, 1)) * 85.0
        return TaskProgress(
            current_chunk=self.current_chunk,
            total_chunks=self.total_chunks,
            percent=round(percent, 1),
        )


class TaskStore:
    def __init__(
        self,
        pipeline: PipelineService,
        persistence: PersistenceService,
        evaluator: EvaluatorService | None = None,
        compliance: ComplianceService | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._evaluator = evaluator
        self._compliance = compliance
        self._persistence = persistence
        self._tasks: dict[str, TaskInfo] = {}
        self._hash_index: dict[str, str] = persistence.load_hash_index()

    @property
    def persistence(self) -> PersistenceService:
        return self._persistence

    # -- hash dedup ----------------------------------------------------------

    def lookup_by_hash(self, file_hash: str) -> str | None:
        """Return existing task_id for the given file hash, or None."""
        task_id = self._hash_index.get(file_hash)
        if task_id is None:
            return None
        if self._persistence.has_file(task_id, "transcript.json"):
            return task_id
        # stale index entry
        del self._hash_index[file_hash]
        self._persistence.save_hash_index(self._hash_index)
        return None

    def _register_hash(self, file_hash: str, task_id: str) -> None:
        self._hash_index[file_hash] = task_id
        self._persistence.save_hash_index(self._hash_index)

    # -- restore from disk ---------------------------------------------------

    def restore_from_disk(self) -> None:
        """Scan uploads directory and restore completed tasks into memory."""
        for entry in self._persistence.scan_completed_tasks():
            task_id = entry["task_id"]
            if task_id in self._tasks:
                continue

            info = TaskInfo(task_id)
            info.audio_path = entry["audio_path"]

            if entry["has_transcript"]:
                data = self._persistence.load_json(task_id, "transcript.json")
                if data:
                    info.result = TranscriptResponse.model_validate(data)
                    info.status = TaskStatus.COMPLETED

            if info.status != TaskStatus.COMPLETED:
                continue

            self._tasks[task_id] = info
            logger.info("Restored task %s from disk", task_id)

        logger.info("Total tasks in memory: %d", len(self._tasks))

    # -- submit methods ------------------------------------------------------

    def submit(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
    ) -> str:
        task_id = uuid.uuid4().hex
        self._tasks[task_id] = TaskInfo(task_id)
        asyncio.create_task(
            self._run_transcription(task_id, audio_bytes, filename, hotwords)
        )
        logger.info("Task %s submitted (transcription)", task_id)
        return task_id

    def submit_evaluation(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
    ) -> str:
        if self._evaluator is None:
            raise RuntimeError("EvaluatorService not configured")
        task_id = uuid.uuid4().hex
        self._tasks[task_id] = TaskInfo(task_id)
        asyncio.create_task(
            self._run_evaluation(task_id, audio_bytes, filename, hotwords)
        )
        logger.info("Task %s submitted (evaluation)", task_id)
        return task_id

    def submit_transcript(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
        *,
        file_hash: str = "",
    ) -> str:
        task_id = uuid.uuid4().hex
        self._tasks[task_id] = TaskInfo(task_id)
        asyncio.create_task(
            self._run_transcript(task_id, audio_bytes, filename, hotwords)
        )
        if file_hash:
            self._register_hash(file_hash, task_id)
        logger.info("Task %s submitted (transcript)", task_id)
        return task_id

    def submit_text_evaluation(
        self,
        text: str,
        *,
        parent_task_id: str | None = None,
    ) -> str:
        """Submit text-only evaluation (no ASR needed)."""
        if self._evaluator is None:
            raise RuntimeError("EvaluatorService not configured")
        task_id = uuid.uuid4().hex
        self._tasks[task_id] = TaskInfo(
            task_id, eval_only=True, parent_task_id=parent_task_id
        )
        asyncio.create_task(self._run_text_evaluation(task_id, text))
        logger.info("Task %s submitted (text evaluation, parent=%s)", task_id, parent_task_id)
        return task_id

    def submit_compliance_audit(
        self,
        transcript_entries: list[dict],
        rules_bytes: bytes,
        rules_filename: str,
        *,
        parent_task_id: str | None = None,
    ) -> str:
        """Submit compliance audit task (text-only, no ASR needed)."""
        if self._compliance is None:
            raise RuntimeError("ComplianceService not configured")
        task_id = uuid.uuid4().hex
        self._tasks[task_id] = TaskInfo(
            task_id, eval_only=True, parent_task_id=parent_task_id
        )
        asyncio.create_task(
            self._run_compliance_audit(
                task_id, transcript_entries, rules_bytes, rules_filename
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
        """Re-run ASR + correction on existing audio. Returns same task_id."""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        audio_path = self._persistence.find_audio(task_id)
        if audio_path is None:
            raise ValueError(f"Audio not found for task {task_id}")

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
            self._run_transcript(task_id, audio_bytes, f"audio{suffix}", hotwords)
        )
        logger.info("Task %s rerun (transcript)", task_id)
        return task_id

    def rerun_evaluation(self, parent_task_id: str) -> str:
        """Re-run evaluation from existing transcript. Returns child task_id."""
        data = self._persistence.load_json(parent_task_id, "transcript.json")
        if data is None:
            raise ValueError(f"transcript.json not found for task {parent_task_id}")

        transcript = TranscriptResponse.model_validate(data)
        full_text = "\n".join(e.text_corrected for e in transcript.transcript)
        if not full_text.strip():
            raise ValueError("Transcript text is empty")

        self._persistence.delete_file(parent_task_id, "evaluation.json")
        return self.submit_text_evaluation(full_text, parent_task_id=parent_task_id)

    # -- get -----------------------------------------------------------------

    def get(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

    # -- run implementations -------------------------------------------------

    async def _run_transcription(
        self,
        task_id: str,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None,
    ) -> None:
        task = self._tasks[task_id]
        try:
            task.status = TaskStatus.PROCESSING_ASR

            def on_progress(current: int, total: int) -> None:
                task.status = TaskStatus.CORRECTING
                task.current_chunk = current
                task.total_chunks = total

            result = await self._pipeline.process(
                audio_bytes, filename, hotwords, on_progress=on_progress
            )

            task.result = TranscriptionResponse(
                raw_text=result.raw_text,
                corrected_text=result.corrected_text,
                segments=[
                    SegmentSchema(
                        text=s.text,
                        start_ms=s.start_ms,
                        end_ms=s.end_ms,
                        confidence=s.confidence,
                    )
                    for s in result.segments
                ],
                processing_time_ms=result.processing_time_ms,
            )
            task.status = TaskStatus.COMPLETED
            logger.info("Task %s completed (transcription)", task_id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error("Task %s failed: %s", task_id, e)

    async def _run_evaluation(
        self,
        task_id: str,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None,
    ) -> None:
        task = self._tasks[task_id]
        try:
            task.status = TaskStatus.PROCESSING_ASR

            def on_progress(current: int, total: int) -> None:
                task.status = TaskStatus.CORRECTING
                task.current_chunk = current
                task.total_chunks = total

            result = await self._pipeline.process(
                audio_bytes, filename, hotwords, on_progress=on_progress
            )

            task.status = TaskStatus.EVALUATING
            task.current_chunk = 0
            task.total_chunks = 0
            assert self._evaluator is not None

            def on_eval_progress(current: int, total: int) -> None:
                task.current_chunk = current
                task.total_chunks = total

            evaluation = await self._evaluator.evaluate(
                result.corrected_text, on_progress=on_eval_progress
            )

            task.result = EvaluationResponse(
                raw_text=result.raw_text,
                corrected_text=result.corrected_text,
                evaluation=evaluation,
                processing_time_ms=result.processing_time_ms,
            )
            task.status = TaskStatus.COMPLETED
            logger.info("Task %s completed (evaluation)", task_id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e) or type(e).__name__
            logger.error("Task %s failed: [%s] %s", task_id, type(e).__name__, e, exc_info=True)

    async def _run_text_evaluation(self, task_id: str, text: str) -> None:
        task = self._tasks[task_id]
        try:
            task.status = TaskStatus.EVALUATING
            task.current_chunk = 0
            task.total_chunks = 0
            assert self._evaluator is not None

            def on_eval_progress(current: int, total: int) -> None:
                task.current_chunk = current
                task.total_chunks = total

            evaluation = await self._evaluator.evaluate(
                text, on_progress=on_eval_progress
            )

            task.result = EvaluationResponse(
                raw_text="",
                corrected_text=text,
                evaluation=evaluation,
                processing_time_ms=0,
            )
            task.status = TaskStatus.COMPLETED

            if task.parent_task_id:
                self._persistence.save_json(
                    task.parent_task_id, "evaluation.json", evaluation
                )

            logger.info("Task %s completed (text evaluation)", task_id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e) or type(e).__name__
            logger.error("Task %s failed: [%s] %s", task_id, type(e).__name__, e, exc_info=True)

    async def _run_transcript(
        self,
        task_id: str,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None,
    ) -> None:
        logger.info("Task %s starting execution (transcript)", task_id)
        task = self._tasks[task_id]
        try:
            task.status = TaskStatus.PROCESSING_ASR
            logger.info("Task %s status: PROCESSING_ASR", task_id)

            def on_progress(current: int, total: int) -> None:
                task.status = TaskStatus.CORRECTING
                task.current_chunk = current
                task.total_chunks = total

            result = await self._pipeline.process_transcript(
                audio_bytes, filename, hotwords, on_progress=on_progress
            )

            transcript_response = TranscriptResponse(
                transcript=[
                    TranscriptEntrySchema(
                        timestamp=entry.timestamp,
                        timestamp_ms=entry.timestamp_ms,
                        speaker=entry.speaker,
                        text=entry.text,
                        text_corrected=entry.text_corrected,
                    )
                    for entry in result.transcript
                ],
                processing_time_ms=result.processing_time_ms,
            )
            task.result = transcript_response
            task.status = TaskStatus.COMPLETED

            self._persistence.save_json(task_id, "transcript.json", transcript_response)

            logger.info("Task %s completed (transcript)", task_id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error("Task %s failed: %s", task_id, e)

    async def _run_compliance_audit(
        self,
        task_id: str,
        transcript_entries: list[dict],
        rules_bytes: bytes,
        rules_filename: str,
    ) -> None:
        import time

        task = self._tasks[task_id]
        try:
            task.status = TaskStatus.AUDITING
            task.current_chunk = 0
            task.total_chunks = 0
            assert self._compliance is not None

            start = time.perf_counter()
            rules, few_shot_examples = self._compliance.parse_rules(
                rules_bytes, rules_filename
            )

            def on_audit_progress(current: int, total: int) -> None:
                task.current_chunk = current
                task.total_chunks = total

            report = await self._compliance.audit(
                rules,
                transcript_entries,
                few_shot_examples=few_shot_examples,
                on_progress=on_audit_progress,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            compliance_response = ComplianceResponse(
                rules=rules,
                report=report,
                processing_time_ms=elapsed_ms,
            )
            task.result = compliance_response
            task.status = TaskStatus.COMPLETED

            if task.parent_task_id:
                self._persistence.save_json(
                    task.parent_task_id, "compliance.json", compliance_response
                )

            logger.info("Task %s completed (compliance audit)", task_id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e) or type(e).__name__
            logger.error(
                "Task %s failed: [%s] %s",
                task_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
