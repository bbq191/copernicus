from fastapi import APIRouter, Form, HTTPException

from copernicus.dependencies import get_task_store
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.task_store import TaskStore

from fastapi import Depends

router = APIRouter(prefix="/api/v1", tags=["evaluation"])


@router.post("/evaluate/text/async", response_model=TaskSubmitResponse, status_code=202)
async def submit_text_evaluation_task(
    text: str = Form(...),
    parent_task_id: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Submit an async text evaluation task. Poll GET /tasks/{task_id} for progress."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    task_id = store.submit_text_evaluation(text, parent_task_id=parent_task_id)
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)
