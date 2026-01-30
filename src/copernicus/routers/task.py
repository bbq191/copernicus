import json

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException

from copernicus.config import settings
from copernicus.dependencies import get_task_store
from copernicus.schemas.task import (
    TaskStatus,
    TaskStatusResponse,
    TaskSubmitResponse,
)
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1", tags=["tasks"])


def _parse_hotwords(hotwords: str | None) -> list[str] | None:
    if not hotwords:
        return None
    try:
        parsed = json.loads(hotwords)
        if isinstance(parsed, list) and all(isinstance(w, str) for w in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    raise HTTPException(status_code=422, detail="hotwords must be a JSON array of strings")


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

    hw = _parse_hotwords(hotwords)
    task_id = store.submit(audio_bytes, file.filename or "upload.bin", hw)

    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


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
