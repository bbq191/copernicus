"""自定义合规规则库：rules_dir 下每条规则一个 JSON 文件，CRUD 式持久化。

与每次任务上传、用完即弃的 CSV/XLSX 规则不同，这里的规则跨任务复用，
且由管理员直接声明 category/check_mode/evidence_sources 等结构化元数据，
提交合规审核时可以整体选用，不需要再靠规则文本去模糊匹配内置规则。

id 从 1000 起自增，与内置的 13 条规则（1-13）不会冲突。
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from copernicus.schemas.compliance import CustomRule, CustomRuleCreate, CustomRuleUpdate
from copernicus.utils.atomic_write import atomic_write

logger = logging.getLogger(__name__)

_ID_START = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuleStore:
    def __init__(self, rules_dir: Path) -> None:
        self._dir = rules_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, rule_id: int) -> Path:
        return self._dir / f"{rule_id}.json"

    def list_rules(self) -> list[CustomRule]:
        """按 id 升序返回全部规则（含已停用的；由调用方按需过滤 enabled）。"""
        rules = []
        for f in self._dir.glob("*.json"):
            try:
                rules.append(CustomRule.model_validate_json(f.read_text("utf-8")))
            except (ValueError, OSError) as e:
                logger.warning("Skipping unreadable rule file %s: %s", f, e)
        rules.sort(key=lambda r: r.id)
        return rules

    def get_rule(self, rule_id: int) -> CustomRule | None:
        path = self._path(rule_id)
        if not path.exists():
            return None
        try:
            return CustomRule.model_validate_json(path.read_text("utf-8"))
        except (ValueError, OSError) as e:
            logger.warning("Failed to read rule %s: %s", rule_id, e)
            return None

    def create_rule(self, data: CustomRuleCreate) -> CustomRule:
        now = _now()
        rule = CustomRule(id=self._next_id(), created_at=now, updated_at=now, **data.model_dump())
        atomic_write(self._path(rule.id), rule.model_dump_json(indent=2))
        return rule

    def update_rule(self, rule_id: int, data: CustomRuleUpdate) -> CustomRule | None:
        existing = self.get_rule(rule_id)
        if existing is None:
            return None
        changes = data.model_dump(exclude_unset=True)
        changes["updated_at"] = _now()
        updated = existing.model_copy(update=changes)
        atomic_write(self._path(rule_id), updated.model_dump_json(indent=2))
        return updated

    def delete_rule(self, rule_id: int) -> bool:
        path = self._path(rule_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _next_id(self) -> int:
        # 先扫描目录再在 create_rule 里写文件，中间无锁：假定单进程（部署固定 --workers 1，
        # 见 copernicus-backend.service.in），多进程并发调用会撞到同一个 id 导致规则互相覆盖。
        existing = [int(f.stem) for f in self._dir.glob("*.json") if f.stem.isdigit()]
        return max(existing, default=_ID_START - 1) + 1
