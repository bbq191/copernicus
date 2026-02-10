from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException

from copernicus.config import settings
from copernicus.dependencies import get_pipeline
from copernicus.exceptions import CopernicusError
from copernicus.schemas.transcription import (
    HealthResponse,
    TranscriptEntrySchema,
    TranscriptResponse,
)
from copernicus.services.pipeline import PipelineService
from copernicus.utils.request import parse_hotwords

router = APIRouter(prefix="/api/v1", tags=["transcription"])


@router.post("/transcribe/transcript", response_model=TranscriptResponse)
async def transcribe_transcript(
    file: UploadFile = File(...),
    hotwords: str | None = Form(default=None),
    pipeline: PipelineService = Depends(get_pipeline),
) -> TranscriptResponse:
    """Upload an audio file and get speaker-segmented transcript with timestamps."""
    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    try:
        hw = parse_hotwords(hotwords)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        result = await pipeline.process_transcript(audio_bytes, file.filename or "upload.bin", hw)
    except CopernicusError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return TranscriptResponse(
        transcript=[
            TranscriptEntrySchema(
                timestamp=entry.timestamp,
                timestamp_ms=entry.timestamp_ms,
                speaker=entry.speaker,
                text=entry.text,
                text_corrected=entry.text_corrected,
            )
            for entry in result.transcript
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
