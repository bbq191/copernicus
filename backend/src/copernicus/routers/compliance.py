import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from copernicus.dependencies import get_task_store
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1", tags=["compliance"])


@router.post(
    "/compliance/audit/async",
    response_model=TaskSubmitResponse,
    status_code=202,
)
async def submit_compliance_audit(
    rules_file: UploadFile = File(..., description="CSV/XLSX compliance rules file"),
    transcript: str = Form(..., description="JSON array of transcript entries"),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Submit async compliance audit task.

    Accepts transcript entries (JSON) and a rules file (CSV/XLSX).
    Poll GET /tasks/{task_id} for progress and result.
    """
    rules_bytes = await rules_file.read()
    if len(rules_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Rules file too large (max 2MB)")

    try:
        entries = json.loads(transcript)
        if not isinstance(entries, list):
            raise ValueError("transcript must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid transcript JSON: {e}")

    if not entries:
        raise HTTPException(status_code=422, detail="Transcript entries must not be empty")

    task_id = store.submit_compliance_audit(
        transcript_entries=entries,
        rules_bytes=rules_bytes,
        rules_filename=rules_file.filename or "rules.csv",
    )

    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)
