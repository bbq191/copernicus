import json

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException

from copernicus.config import settings
from copernicus.dependencies import get_pipeline
from copernicus.exceptions import CopernicusError
from copernicus.schemas.transcription import (
    HealthResponse,
    RawTranscriptionResponse,
    SegmentSchema,
    TranscriptionResponse,
)
from copernicus.services.pipeline import PipelineService

router = APIRouter(prefix="/api/v1", tags=["transcription"])


async def _parse_hotwords(hotwords: str | None) -> list[str] | None:
    if not hotwords:
        return None
    try:
        parsed = json.loads(hotwords)
        if isinstance(parsed, list) and all(isinstance(w, str) for w in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    raise HTTPException(status_code=422, detail="hotwords must be a JSON array of strings")


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    file: UploadFile = File(...),
    hotwords: str | None = Form(default=None),
    pipeline: PipelineService = Depends(get_pipeline),
) -> TranscriptionResponse:
    """Upload an audio file and get ASR + LLM-corrected transcription."""
    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    hw = await _parse_hotwords(hotwords)

    try:
        result = await pipeline.process(audio_bytes, file.filename or "upload.bin", hw)
    except CopernicusError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return TranscriptionResponse(
        raw_text=result.raw_text,
        corrected_text=result.corrected_text,
        segments=[
            SegmentSchema(text=s.text, start_ms=s.start_ms, end_ms=s.end_ms)
            for s in result.segments
        ],
        processing_time_ms=result.processing_time_ms,
    )


@router.post("/transcribe/raw", response_model=RawTranscriptionResponse)
async def transcribe_raw(
    file: UploadFile = File(...),
    hotwords: str | None = Form(default=None),
    pipeline: PipelineService = Depends(get_pipeline),
) -> RawTranscriptionResponse:
    """Upload an audio file and get raw ASR transcription (no LLM correction)."""
    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    hw = await _parse_hotwords(hotwords)

    try:
        result = await pipeline.process_raw(audio_bytes, file.filename or "upload.bin", hw)
    except CopernicusError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RawTranscriptionResponse(
        raw_text=result.raw_text,
        segments=[
            SegmentSchema(text=s.text, start_ms=s.start_ms, end_ms=s.end_ms)
            for s in result.segments
        ],
        processing_time_ms=result.processing_time_ms,
    )


@router.get("/health", response_model=HealthResponse)
async def health(
    pipeline: PipelineService = Depends(get_pipeline),
) -> HealthResponse:
    """Check service health: ASR model loaded and LLM reachable."""
    asr_loaded = pipeline._asr is not None
    llm_reachable = await pipeline._corrector.is_reachable()
    return HealthResponse(asr_loaded=asr_loaded, llm_reachable=llm_reachable)
