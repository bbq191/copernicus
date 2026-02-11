import hashlib
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from copernicus.config import settings
from copernicus.dependencies import get_task_store
from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResult
from copernicus.schemas.task import (
    TaskStatus,
    TaskStatusResponse,
    TaskSubmitResponse,
    TaskResultsResponse,
)
from copernicus.schemas.transcription import TranscriptResponse
from copernicus.services.task_store import TaskStore
from copernicus.utils.request import parse_hotwords

_VIDEO_EXTENSIONS = {
    e.strip().lower()
    for e in settings.video_extensions.split(",")
    if e.strip()
}

router = APIRouter(prefix="/api/v1", tags=["tasks"])


@router.post("/tasks/transcript", response_model=TaskSubmitResponse, status_code=202)
async def submit_transcript_task(
    file: UploadFile = File(...),
    hotwords: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Submit an async transcript task with timestamps and speaker labels."""
    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    # file dedup via SHA-256
    file_hash = hashlib.sha256(audio_bytes).hexdigest()
    existing_id = store.lookup_by_hash(file_hash)
    if existing_id:
        return TaskSubmitResponse(
            task_id=existing_id, status=TaskStatus.COMPLETED, existing=True
        )

    try:
        hw = parse_hotwords(hotwords)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    task_id = store.submit_transcript(
        audio_bytes, file.filename or "upload.bin", hw, file_hash=file_hash
    )

    # persist media and meta to task directory
    persistence = store.persistence
    filename = file.filename or "upload.bin"
    suffix = Path(filename).suffix or ".bin"
    is_video = suffix.lower() in _VIDEO_EXTENSIONS

    if is_video:
        video_path = persistence.save_video(task_id, audio_bytes, suffix)
        persistence.save_meta(
            task_id,
            filename=filename,
            file_hash=file_hash,
            audio_suffix=suffix,
            media_type="video",
            video_suffix=suffix,
        )
        task = store.get(task_id)
        if task:
            task.audio_path = str(video_path)
    else:
        audio_path = persistence.save_audio(task_id, audio_bytes, suffix)
        persistence.save_meta(
            task_id, filename=filename, file_hash=file_hash, audio_suffix=suffix
        )
        task = store.get(task_id)
        if task:
            task.audio_path = str(audio_path)

    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.get("/tasks/{task_id}/media")
async def get_task_media(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """Return the original uploaded media file (audio or video)."""
    persistence = store.persistence

    # Try video first
    video_path = persistence.find_video(task_id)
    if video_path and video_path.exists():
        mime = mimetypes.guess_type(str(video_path))[0] or "video/mp4"
        return FileResponse(video_path, media_type=mime)

    # Fall back to audio
    audio_path = persistence.find_audio(task_id)
    if audio_path and audio_path.exists():
        mime = mimetypes.guess_type(str(audio_path))[0] or "audio/mpeg"
        return FileResponse(audio_path, media_type=mime)

    # Legacy fallback
    task = store.get(task_id)
    if task and task.audio_path:
        legacy = Path(task.audio_path)
        if legacy.exists():
            mime = mimetypes.guess_type(str(legacy))[0] or "audio/mpeg"
            return FileResponse(legacy, media_type=mime)

    raise HTTPException(status_code=404, detail="Media file not found")


@router.get("/tasks/{task_id}/audio")
async def get_task_audio(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """Backward-compatible audio endpoint -- delegates to media logic."""
    return await get_task_media(task_id, store)


@router.get("/tasks/{task_id}/frames/{filename}")
async def get_task_frame(
    task_id: str,
    filename: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """Return a keyframe image."""
    frames_path = store.persistence.task_dir(task_id) / "frames" / filename
    if not frames_path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")
    mime = mimetypes.guess_type(str(frames_path))[0] or "image/jpeg"
    return FileResponse(frames_path, media_type=mime)


@router.get("/tasks/{task_id}/results", response_model=TaskResultsResponse)
async def get_task_results(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> TaskResultsResponse:
    """Return all persisted results for a task."""
    persistence = store.persistence

    if not persistence.has_file(task_id, "meta.json"):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

    transcript = None
    transcript_data = persistence.load_json(task_id, "transcript.json")
    if transcript_data:
        transcript = TranscriptResponse.model_validate(transcript_data)

    evaluation = None
    eval_data = persistence.load_json(task_id, "evaluation.json")
    if eval_data:
        evaluation = EvaluationResult.model_validate(eval_data)

    compliance = None
    compliance_data = persistence.load_json(task_id, "compliance.json")
    if compliance_data:
        compliance = ComplianceResponse.model_validate(compliance_data)

    has_audio = persistence.find_audio(task_id) is not None
    has_video = persistence.find_video(task_id) is not None
    frames_path = persistence.task_dir(task_id) / "frames"
    keyframe_count = len(list(frames_path.glob("*"))) if frames_path.is_dir() else 0

    ocr_data = persistence.load_json(task_id, "ocr_results.json")
    ocr_text_count = len(ocr_data) if isinstance(ocr_data, list) else 0

    events_data = persistence.load_json(task_id, "visual_events.json")
    visual_event_count = len(events_data) if isinstance(events_data, list) else 0

    return TaskResultsResponse(
        task_id=task_id,
        transcript=transcript,
        evaluation=evaluation,
        compliance=compliance,
        has_audio=has_audio,
        has_video=has_video,
        keyframe_count=keyframe_count,
        ocr_text_count=ocr_text_count,
        visual_event_count=visual_event_count,
    )


@router.post("/tasks/{task_id}/rerun-transcript", response_model=TaskSubmitResponse)
async def rerun_transcript(
    task_id: str,
    hotwords: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Re-run ASR + correction on existing audio."""
    try:
        hw = parse_hotwords(hotwords)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        store.rerun_transcript(task_id, hw)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.post("/tasks/{task_id}/rerun-evaluation", response_model=TaskSubmitResponse)
async def rerun_evaluation(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Re-run evaluation based on existing transcript."""
    try:
        child_task_id = store.rerun_evaluation(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return TaskSubmitResponse(task_id=child_task_id, status=TaskStatus.PENDING)


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> TaskStatusResponse:
    """Query task progress and result."""
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        progress=task.progress,
        result=task.result,
        error=task.error,
    )
