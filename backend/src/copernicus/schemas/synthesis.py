from pydantic import BaseModel


class SynthesisRequest(BaseModel):
    voice_map: dict[str, str] | None = None


class SynthesisResponse(BaseModel):
    audio_url: str
    duration_ms: float
    synthesis_time_ms: float
