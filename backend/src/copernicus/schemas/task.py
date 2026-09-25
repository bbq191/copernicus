from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResponse, EvaluationResult
from copernicus.schemas.transcription import (
    MAX_SPEAKER_NAME_LEN,
    MAX_TRANSCRIPT_TEXT_LEN,
    TranscriptResponse,
)


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
    has_synthesis: bool = False
    keyframe_count: int = 0
    ocr_text_count: int = 0
    visual_event_count: int = 0


class TaskSummary(BaseModel):
    """历史任务列表条目。"""

    task_id: str
    name: str  # 优先级：用户重命名 > 纪要标题 > 原始文件名
    filename: str
    created_at: str
    status: TaskStatus
    error: str | None = None
    has_video: bool = False
    has_evaluation: bool = False
    has_compliance: bool = False


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]
    total: int  # 磁盘上的任务总数（大于 len(tasks) 表示被 limit 截断）


class TaskRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TranscriptTextEdit(BaseModel):
    index: int = Field(ge=0, description="句段在转写列表中的下标")
    text_corrected: str = Field(max_length=MAX_TRANSCRIPT_TEXT_LEN)


class TranscriptEditRequest(BaseModel):
    edits: list[TranscriptTextEdit] = Field(min_length=1, max_length=2000)


class SpeakerRenameRequest(BaseModel):
    """{原说话人: 新名称}；多个原名映射到同一新名称即合并说话人。"""

    renames: dict[str, str] = Field(min_length=1, max_length=50)

    @field_validator("renames")
    @classmethod
    def _clean_names(cls, renames: dict[str, str]) -> dict[str, str]:
        cleaned = {old: new.strip() for old, new in renames.items()}
        if any(not n or len(n) > MAX_SPEAKER_NAME_LEN for n in cleaned.values()):
            raise ValueError(f"说话人名称不能为空且不超过 {MAX_SPEAKER_NAME_LEN} 字符")
        return cleaned


class TranscriptUpdateResponse(BaseModel):
    updated: int
