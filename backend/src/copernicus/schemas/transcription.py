from typing import Literal

from pydantic import BaseModel


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
