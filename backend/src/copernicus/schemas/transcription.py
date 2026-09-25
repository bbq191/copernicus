from typing import Literal

from pydantic import BaseModel

# 人工校对的输入上限
MAX_SPEAKER_NAME_LEN = 50
MAX_TRANSCRIPT_TEXT_LEN = 5000


class ComponentStatus(BaseModel):
    status: Literal["ok", "degraded", "down"]
    detail: str | None = None


class TaskStats(BaseModel):
    active: int
    completed: int
    failed: int
    synthesis_running: int


class VramStatus(BaseModel):
    loaded_models: list[str]
    estimated_used_gb: float
    budget_gb: float


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    asr: ComponentStatus
    llm: ComponentStatus
    tts: ComponentStatus | None = None
    tasks: TaskStats
    vram: VramStatus | None = None


class TranscriptEntrySchema(BaseModel):
    timestamp: str
    timestamp_ms: int
    end_ms: int = 0
    speaker: str
    text: str
    text_corrected: str


class TranscriptResponse(BaseModel):
    transcript: list[TranscriptEntrySchema]
    processing_time_ms: float
    # LLM 润色的批次统计；failed > 0 时部分文本未经润色（旧数据无此字段，按 0 处理）
    correction_total_batches: int = 0
    correction_failed_batches: int = 0
