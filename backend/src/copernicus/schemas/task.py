from enum import StrEnum

from pydantic import BaseModel

from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResponse, EvaluationResult
from copernicus.schemas.transcription import TranscriptResponse


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING_ASR = "processing_asr"
    EXTRACTING_FRAMES = "extracting_frames"
    SCANNING_VISUAL = "scanning_visual"
    CORRECTING = "correcting"
    EVALUATING = "evaluating"
    AUDITING = "auditing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: TaskStatus
    existing: bool = False


class TaskProgress(BaseModel):
    current_chunk: int = 0
    total_chunks: int = 0
    percent: float = 0.0


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: TaskProgress
    result: EvaluationResponse | TranscriptResponse | ComplianceResponse | None = None
    error: str | None = None


class TaskResultsResponse(BaseModel):
    """Persisted results for a task (used for restoring state on page refresh)."""

    task_id: str
    transcript: TranscriptResponse | None = None
    evaluation: EvaluationResult | None = None
    compliance: ComplianceResponse | None = None
    has_audio: bool = False
    has_video: bool = False
    keyframe_count: int = 0
    ocr_text_count: int = 0
    visual_event_count: int = 0
