from enum import StrEnum

from pydantic import BaseModel

from copernicus.schemas.evaluation import EvaluationResponse
from copernicus.schemas.transcription import TranscriptionResponse


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING_ASR = "processing_asr"
    CORRECTING = "correcting"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: TaskStatus


class TaskProgress(BaseModel):
    current_chunk: int = 0
    total_chunks: int = 0
    percent: float = 0.0


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: TaskProgress
    result: TranscriptionResponse | EvaluationResponse | None = None
    error: str | None = None
