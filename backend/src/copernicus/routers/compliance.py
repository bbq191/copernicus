import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from copernicus.dependencies import get_task_store
from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1", tags=["高阶 AI"])


@router.post(
    "/tasks/compliance_audit",
    response_model=TaskSubmitResponse,
    status_code=202,
    summary="提交合规审核任务",
)
async def submit_compliance_audit(
    rules_file: UploadFile = File(..., description="CSV 或 XLSX 格式的规则文件，最大 2 MB"),
    transcript: str = Form(..., description="转写条目 JSON 数组，来自 /tasks/{id}/results"),
    parent_task_id: str | None = Form(default=None, description="关联的转写任务 ID，用于自动加载 OCR/视觉数据"),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """对转写文本执行多模态合规推理（Advanced AI 层）。

    **流程**：规则解析 → 卸载 ASR（释放 2 GB VRAM）→ Map-Reduce 逐规则审核
    → 过滤链（去重 + 置信度过滤）→ 汇总打分。

    **`rules_file`**：支持 CSV / XLSX，需包含规则 ID、规则内容、few-shot 示例列。

    **`transcript`**：调用 `GET /tasks/{task_id}/results` 后取
    `transcript.transcript` 字段序列化为 JSON 字符串。

    **`parent_task_id`**：填写后自动从持久化层加载对应任务的
    `ocr_results.json` 和 `visual_events.json`，融入多模态推理。
    结果写入该任务的 `compliance.json`。
    """
    rules_bytes = await rules_file.read()
    if len(rules_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Rules file too large (max 2MB)")

    if len(transcript.encode()) > 500 * 1024:
        raise HTTPException(status_code=413, detail="Transcript too large (max 500 KB)")

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


@router.patch(
    "/tasks/{task_id}/compliance/violations",
    summary="批量更新违规审核状态",
)
async def update_violation_statuses(
    task_id: str,
    body: ViolationBatchUpdate,
    store: TaskStore = Depends(get_task_store),
) -> dict:
    """人工复核时更新违规条目的状态。

    `status` 取值：`pending`（待审）、`confirmed`（已确认）、`rejected`（已驳回）。
    更新立即持久化到 `compliance.json`，页面刷新后状态保留。
    """
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
