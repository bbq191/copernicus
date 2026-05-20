from pydantic import BaseModel


class SynthesisRequest(BaseModel):
    voice_map: dict[str, str] | None = None


class SynthesisResponse(BaseModel):
    audio_url: str
    duration_ms: float
    synthesis_time_ms: float


class SynthesisStatusResponse(BaseModel):
    status: str  # "running" | "completed" | "failed"
    error: str | None = None
    audio_url: str | None = None
    duration_ms: float | None = None
    synthesis_time_ms: float | None = None
