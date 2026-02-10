import hashlib
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

router = APIRouter(prefix="/api/v1", tags=["tasks"])


@router.post("/tasks", response_model=TaskSubmitResponse, status_code=202)
async def submit_task(
    file: UploadFile = File(...),
    hotwords: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Submit an async transcription task. Returns task_id immediately."""
    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    hw = parse_hotwords(hotwords)
    task_id = store.submit(audio_bytes, file.filename or "upload.bin", hw)

    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


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

    hw = parse_hotwords(hotwords)
    task_id = store.submit_transcript(
        audio_bytes, file.filename or "upload.bin", hw, file_hash=file_hash
    )

    # persist audio and meta to task directory
    persistence = store.persistence
    filename = file.filename or "upload.bin"
    suffix = Path(filename).suffix or ".bin"
    audio_path = persistence.save_audio(task_id, audio_bytes, suffix)
    persistence.save_meta(
        task_id, filename=filename, file_hash=file_hash, audio_suffix=suffix
    )

    task = store.get(task_id)
    if task:
        task.audio_path = str(audio_path)

    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.get("/tasks/{task_id}/audio")
async def get_task_audio(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """Return the original uploaded audio file for playback."""
    audio_path = store.persistence.find_audio(task_id)
    if audio_path and audio_path.exists():
        return FileResponse(audio_path, media_type="audio/mpeg")

    # fallback: check TaskInfo.audio_path (legacy)
    task = store.get(task_id)
    if task and task.audio_path:
        legacy = Path(task.audio_path)
        if legacy.exists():
            return FileResponse(legacy, media_type="audio/mpeg")

    raise HTTPException(status_code=404, detail="Audio file not found")


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

    return TaskResultsResponse(
        task_id=task_id,
        transcript=transcript,
        evaluation=evaluation,
        compliance=compliance,
        has_audio=has_audio,
    )


@router.post("/tasks/{task_id}/rerun-transcript", response_model=TaskSubmitResponse)
async def rerun_transcript(
    task_id: str,
    hotwords: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Re-run ASR + correction on existing audio."""
    hw = parse_hotwords(hotwords)
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
