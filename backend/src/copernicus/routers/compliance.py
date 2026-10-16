import json
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, model_validator

from copernicus.dependencies import get_rule_store, get_task_store
from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.compliance_export import build_compliance_xlsx
from copernicus.services.rule_store import RuleStore
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1", tags=["高阶 AI"])


@router.post(
    "/tasks/compliance_audit",
    response_model=TaskSubmitResponse,
    status_code=202,
    summary="提交合规审核任务",
)
async def submit_compliance_audit(
    rules_file: UploadFile | None = File(
        default=None, description="CSV 或 XLSX 格式的规则文件，最大 2 MB；省略时须将 use_rule_library 设为 true"
    ),
    use_rule_library: bool = Form(
        default=False, description="不提供 rules_file 时，使用规则库（/api/v1/rules）中已启用的规则"
    ),
    transcript: str = Form(..., description="转写条目 JSON 数组，来自 /tasks/{id}/results"),
    parent_task_id: str | None = Form(default=None, description="关联的转写任务 ID，用于自动加载 OCR 证据"),
    store: TaskStore = Depends(get_task_store),
    rule_store: RuleStore = Depends(get_rule_store),
) -> TaskSubmitResponse:
    """对转写文本执行合规推理（Advanced AI 层）。

    **流程**：规则解析 → 卸载 ASR（释放 2 GB VRAM）→ Map-Reduce 逐规则审核
    → 过滤链（去重 + 置信度过滤）→ 汇总打分。

    **`rules_file`**：支持 CSV / XLSX，需包含规则 ID、规则内容、few-shot 示例列。
    省略时须将 `use_rule_library` 设为 `true`，改用规则库里已启用的自定义规则
    （带完整的 category/check_mode/evidence_sources 元数据，不需要再靠内容模糊匹配）；
    两者二选一，不会合并使用。

    **`transcript`**：调用 `GET /tasks/{task_id}/results` 后取
    `transcript.transcript` 字段序列化为 JSON 字符串。

    **`parent_task_id`**：填写后自动从持久化层加载对应任务的
    `ocr_results.json` 作为画面文字证据；若该任务做过人脸检测，`visual_events.json`
    会作为"全程双录"规则（id=4）的证据参与判定。
    结果写入该任务的 `compliance.json`。
    """
    if rules_file is None:
        if not use_rule_library:
            raise HTTPException(
                status_code=422, detail="必须提供 rules_file，或将 use_rule_library 设为 true 使用规则库"
            )
        if not any(r.enabled for r in rule_store.list_rules()):
            raise HTTPException(status_code=422, detail="规则库为空或没有已启用的规则，请先在规则库中添加")
        rules_bytes, rules_filename = b"", ""
    else:
        rules_bytes = await rules_file.read()
        if len(rules_bytes) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Rules file too large (max 2MB)")
        rules_filename = rules_file.filename or "rules.csv"
        use_rule_library = False

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
        rules_filename=rules_filename,
        parent_task_id=parent_task_id,
        use_rule_library=use_rule_library,
    )
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


class ViolationStatusUpdate(BaseModel):
    violation_id: str | None = None
    index: int | None = Field(
        default=None, description="已废弃：列表下标，请改用 violation_id"
    )
    status: Literal["pending", "confirmed", "rejected"] | None = Field(
        default=None, description="不提供时仅更新 assignee/due_at，不触碰复核状态"
    )
    note: str | None = Field(default=None, max_length=500, description="复核备注（如驳回原因）")
    assignee: str | None = Field(
        default=None, max_length=50, description="指派给谁复核；传空字符串清除指派，不提供则不改动"
    )
    due_at: str | None = Field(
        default=None, description="复核截止时间 ISO 8601；传空字符串清除，不提供则不改动"
    )

    @model_validator(mode="after")
    def _require_target(self) -> "ViolationStatusUpdate":
        if self.violation_id is None and self.index is None:
            raise ValueError("violation_id 与 index 至少提供一个")
        return self


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

    通过 `violation_id`（报告内稳定唯一）定位条目；`index`（列表下标）仅为兼容旧客户端保留。
    `status` 取值：`pending`（待审）、`confirmed`（已确认）、`rejected`（已驳回）。
    确认/驳回会记录复核时间 `reviewed_at`，可附 `note` 备注；改回 `pending` 会清空留痕。
    `status` 可省略，此时仅更新 `assignee`/`due_at`（指派复核人/截止时间），不触碰复核状态。
    合规评分随复核重算（已驳回的条目不再扣分），新分数在响应的 `compliance_score` 中返回。
    更新立即持久化到 `compliance.json`，页面刷新后状态保留。
    未匹配到条目的更新会在 `missing` 中返回，不会中断其余更新。
    """
    persistence = store.persistence
    data = persistence.load_json(task_id, "compliance.json")
    if data is None:
        raise HTTPException(status_code=404, detail="compliance.json not found")

    compliance = ComplianceResponse.model_validate(data)
    violations = compliance.report.violations
    by_id = {v.id: v for v in violations}

    updated = 0
    missing: list[str] = []
    for u in body.updates:
        if u.violation_id is not None:
            target = by_id.get(u.violation_id)
        else:
            target = violations[u.index] if 0 <= u.index < len(violations) else None
        if target is None:
            missing.append(u.violation_id if u.violation_id is not None else str(u.index))
            continue
        if u.status is not None:
            target.apply_review(u.status, u.note)
        if u.assignee is not None:
            target.assignee = u.assignee.strip() or None
        if u.due_at is not None:
            target.due_at = u.due_at.strip() or None
        updated += 1

    score = compliance.report.recalculate_score()
    persistence.save_json(task_id, "compliance.json", compliance)
    return {"ok": True, "updated": updated, "missing": missing, "compliance_score": score}


@router.get(
    "/compliance/todos",
    summary="查询指派给某人的待处理违规",
)
async def list_compliance_todos(
    assignee: str,
    store: TaskStore = Depends(get_task_store),
) -> list[dict]:
    """跨任务聚合"指派给我、还没处理"的违规条目，按截止时间升序（无截止时间排最后）。

    没有账户体系，`assignee` 是自由文本姓名，按完全匹配过滤。
    一次性全量扫描 upload_dir 下所有任务的 compliance.json，没有另建索引——
    量级是"一个团队的审核记录"，不是海量数据，扫描足够快，先不为了性能提前做索引。
    """
    todos = []
    for task_id, data in store.persistence.scan_compliance_reports():
        for v in data.get("report", {}).get("violations", []):
            if v.get("assignee") == assignee and v.get("status") == "pending":
                todos.append({**v, "task_id": task_id})
    todos.sort(key=lambda v: v.get("due_at") or "9999-12-31")
    return todos


@router.get(
    "/compliance/analytics/trends",
    summary="合规审核趋势统计",
)
async def compliance_trends(
    store: TaskStore = Depends(get_task_store),
) -> dict:
    """跨任务聚合已持久化的合规审核结果：命中最多的规则、严重度分布、平均合规分。

    一次性全量扫描（见 `scan_compliance_reports`），不是实时指标，量级同 `/compliance/todos`。
    已驳回（人工确认为误报）的条目不计入命中统计，否则高频误报的规则会显得像"高频真实违规"。
    """
    reports = store.persistence.scan_compliance_reports()

    rule_hits: Counter[int] = Counter()
    rule_contents: dict[int, str] = {}
    severity_counts: Counter[str] = Counter()
    scores: list[float] = []

    for _task_id, data in reports:
        report = data.get("report", {})
        scores.append(report.get("compliance_score", 100.0))
        for v in report.get("violations", []):
            if v.get("status") == "rejected":
                continue
            rule_id = v["rule_id"]
            rule_hits[rule_id] += 1
            rule_contents[rule_id] = v.get("rule_content", "")
            severity_counts[v.get("severity", "low")] += 1

    top_rules = [
        {"rule_id": rule_id, "rule_content": rule_contents[rule_id], "count": count}
        for rule_id, count in rule_hits.most_common(20)
    ]
    return {
        "total_tasks": len(reports),
        "avg_compliance_score": round(sum(scores) / len(scores), 1) if scores else None,
        "top_rules": top_rules,
        "severity_counts": dict(severity_counts),
    }


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(
    "/tasks/{task_id}/compliance/export",
    summary="导出合规审核报告（Excel）",
    response_class=Response,
    responses={200: {"content": {_XLSX_MEDIA_TYPE: {}}}},
)
async def export_compliance_report(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> Response:
    """导出包含概览与违规明细两个工作表的 Excel 报告，含人工复核状态、时间与备注。"""
    data = store.persistence.load_json(task_id, "compliance.json")
    if data is None:
        raise HTTPException(status_code=404, detail="compliance.json not found")

    content = build_compliance_xlsx(ComplianceResponse.model_validate(data))
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="compliance_{task_id[:8]}.xlsx"'
        },
    )
