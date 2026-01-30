from pydantic import BaseModel


class SegmentSchema(BaseModel):
    text: str
    start_ms: int
    end_ms: int
    confidence: float = 0.0


class TranscriptionResponse(BaseModel):
    raw_text: str
    corrected_text: str
    segments: list[SegmentSchema]
    processing_time_ms: float


class RawTranscriptionResponse(BaseModel):
    raw_text: str
    segments: list[SegmentSchema]
    processing_time_ms: float


class HealthResponse(BaseModel):
    asr_loaded: bool
    llm_reachable: bool
