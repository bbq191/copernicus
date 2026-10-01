"""自定义合规规则库的 CRUD 管理。

与 /tasks/compliance_audit 每次上传、用完即弃的 CSV/XLSX 规则不同，
这里的规则跨任务持久化，提交审核时可整体选用（见 compliance.py 的 use_rule_library）。
"""

from fastapi import APIRouter, Depends, HTTPException

from copernicus.dependencies import get_rule_store
from copernicus.schemas.compliance import CustomRule, CustomRuleCreate, CustomRuleUpdate
from copernicus.services.rule_store import RuleStore

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
