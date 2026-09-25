"""任务的内存态：状态集合、任务信息（含进度计算）与合成任务记录。"""

from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResponse
from copernicus.schemas.task import TaskProgress, TaskStatus
from copernicus.schemas.transcription import TranscriptResponse

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

    def enter(self, status: TaskStatus) -> None:
        """切换到新阶段并清零该阶段的进度。"""
        self.status = status
        self.current_chunk = 0
        self.total_chunks = 0

    def set_progress(self, current: int, total: int) -> None:
        """阶段内进度回调（可直接作为 on_progress 传入）。"""
        self.current_chunk = current
        self.total_chunks = total

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
        else:  # FAILED：失败时刻的阶段进度已不可知，不显示一个误导性的百分比
            percent = 0.0
        return TaskProgress(
            current_chunk=self.current_chunk,
            total_chunks=self.total_chunks,
            percent=round(percent, 1),
        )


class SynthesisJob:
    __slots__ = ("status", "error", "duration_ms", "synthesis_time_ms")

    def __init__(self) -> None:
        self.status: str = "running"
        self.error: str | None = None
        self.duration_ms: float | None = None
        self.synthesis_time_ms: float | None = None
