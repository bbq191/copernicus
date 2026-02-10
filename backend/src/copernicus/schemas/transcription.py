from pydantic import BaseModel


class HealthResponse(BaseModel):
    asr_loaded: bool
    llm_reachable: bool


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
