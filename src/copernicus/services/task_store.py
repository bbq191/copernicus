import asyncio
import logging
import uuid

from copernicus.schemas.evaluation import EvaluationResponse
from copernicus.schemas.task import TaskProgress, TaskStatus
from copernicus.schemas.transcription import SegmentSchema, TranscriptionResponse
from copernicus.services.evaluator import EvaluatorService
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
    )

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.status = TaskStatus.PENDING
        self.current_chunk = 0
        self.total_chunks = 0
        self.result: TranscriptionResponse | EvaluationResponse | None = None
        self.error: str | None = None

    @property
    def progress(self) -> TaskProgress:
        if self.status == TaskStatus.PENDING:
            percent = 0.0
        elif self.status == TaskStatus.PROCESSING_ASR:
            percent = 5.0
        elif self.status == TaskStatus.CORRECTING and self.total_chunks > 0:
            percent = 5.0 + (self.current_chunk / self.total_chunks) * 85.0
        elif self.status == TaskStatus.EVALUATING:
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
        evaluator: EvaluatorService | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._evaluator = evaluator
        self._tasks: dict[str, TaskInfo] = {}

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

    def get(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

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
            assert self._evaluator is not None
            evaluation = await self._evaluator.evaluate(result.corrected_text)

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
            task.error = str(e)
            logger.error("Task %s failed: %s", task_id, e)
