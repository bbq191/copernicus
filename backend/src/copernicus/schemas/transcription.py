from pydantic import BaseModel


class VramStatus(BaseModel):
    loaded_models: list[str]
    estimated_used_gb: float
    budget_gb: float


class HealthResponse(BaseModel):
    asr_loaded: bool
    llm_reachable: bool
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
