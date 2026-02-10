import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from copernicus.dependencies import get_task_store
from copernicus.schemas.compliance import ComplianceResponse
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
    parent_task_id: str | None = Form(default=None),
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
        parent_task_id=parent_task_id,
    )

    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


class ViolationStatusUpdate(BaseModel):
    index: int
    status: Literal["pending", "confirmed", "rejected"]


class ViolationBatchUpdate(BaseModel):
    updates: list[ViolationStatusUpdate]


@router.patch("/tasks/{task_id}/compliance/violations")
async def update_violation_statuses(
    task_id: str,
    body: ViolationBatchUpdate,
    store: TaskStore = Depends(get_task_store),
) -> dict:
    """Persist violation review statuses (confirmed / rejected / pending)."""
    persistence = store.persistence
    data = persistence.load_json(task_id, "compliance.json")
    if data is None:
        raise HTTPException(status_code=404, detail="compliance.json not found")

    compliance = ComplianceResponse.model_validate(data)
    violations = compliance.report.violations

    for u in body.updates:
        if 0 <= u.index < len(violations):
            violations[u.index].status = u.status

    persistence.save_json(task_id, "compliance.json", compliance)
    return {"ok": True}
