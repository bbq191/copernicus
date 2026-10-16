"""自定义合规规则库的 CRUD 管理。

与 /tasks/compliance_audit 每次上传、用完即弃的 CSV/XLSX 规则不同，
这里的规则跨任务持久化，提交审核时可整体选用（见 compliance.py 的 use_rule_library）。
"""

from fastapi import APIRouter, Depends, HTTPException

from copernicus.dependencies import get_rule_store, get_task_store
from copernicus.schemas.compliance import CustomRule, CustomRuleCreate, CustomRuleUpdate
from copernicus.services.bulk_reaudit import get_job, start_bulk_reaudit
from copernicus.services.rule_store import RuleStore
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1/rules", tags=["合规规则库"])


@router.get("", summary="列出全部自定义规则")
async def list_rules(store: RuleStore = Depends(get_rule_store)) -> list[CustomRule]:
    """按 id 升序返回全部规则，含已停用的（`enabled=false`）。"""
    return store.list_rules()


@router.post("", status_code=201, summary="新增自定义规则")
async def create_rule(
    body: CustomRuleCreate, store: RuleStore = Depends(get_rule_store)
) -> CustomRule:
    """`id` 由服务端从 1000 起自增分配，不与内置的 13 条规则（1-13）冲突。

    `check_mode=exact` 时仅 `keywords` 参与审核判断，建议同时填写 `content`/`description`
    说明场景；自定义规则的 exact 匹配只由 LLM 判断，不会像内置规则一样做正则与拼音二次校验。
    """
    return store.create_rule(body)


@router.get("/reaudit-jobs/{job_id}", summary="查询批量重审进度")
async def get_reaudit_job(job_id: str) -> dict:
    """`done=false` 时客户端应轮询；`diffs` 只包含合规分实际发生变化的任务。"""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "rule_id": job.rule_id,
        "total": len(job.task_ids),
        "completed": job.completed,
        "failed": job.failed,
        "done": job.done,
        "diffs": [
            {"task_id": d.task_id, "old_score": d.old_score, "new_score": d.new_score}
            for d in job.diffs
        ],
    }


@router.get("/{rule_id}", summary="获取单条规则")
async def get_rule(rule_id: int, store: RuleStore = Depends(get_rule_store)) -> CustomRule:
    rule = store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/{rule_id}", summary="更新规则（部分字段）")
async def update_rule(
    rule_id: int, body: CustomRuleUpdate, store: RuleStore = Depends(get_rule_store)
) -> CustomRule:
    """只更新请求体里出现的字段；省略的字段保持不变。`enabled=false` 可临时停用而不必删除。"""
    rule = store.update_rule(rule_id, body)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.delete("/{rule_id}", status_code=204, summary="删除规则")
async def delete_rule(rule_id: int, store: RuleStore = Depends(get_rule_store)) -> None:
    if not store.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")


@router.get("/{rule_id}/affected-tasks", summary="查询引用该规则的历史任务数")
async def count_affected_tasks(
    rule_id: int,
    rule_store: RuleStore = Depends(get_rule_store),
    task_store: TaskStore = Depends(get_task_store),
) -> dict:
    """只统计经规则库提交的审核（`use_rule_library=true`），不含一次性上传 CSV 的审核。"""
    if rule_store.get_rule(rule_id) is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    task_ids = task_store.persistence.scan_task_ids_using_rule(rule_id)
    return {"task_ids": task_ids, "total": len(task_ids)}


@router.post("/{rule_id}/reaudit-affected", status_code=202, summary="批量重新审核受影响的历史任务")
async def reaudit_affected(
    rule_id: int,
    rule_store: RuleStore = Depends(get_rule_store),
    task_store: TaskStore = Depends(get_task_store),
) -> dict:
    """串行逐个重跑，不会并发——不能和实时转写/审核请求抢资源（见 services/bulk_reaudit.py）。

    用 `GET /rules/reaudit-jobs/{job_id}` 轮询进度；完成后 `diffs` 里是合规分实际变化的任务。
    """
    if rule_store.get_rule(rule_id) is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    task_ids = task_store.persistence.scan_task_ids_using_rule(rule_id)
    if not task_ids:
        raise HTTPException(status_code=422, detail="没有历史任务通过规则库引用过这条规则")
    job = start_bulk_reaudit(task_store, rule_id, task_ids)
    return {"job_id": job.id, "total": len(task_ids)}
