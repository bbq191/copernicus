"""自定义合规规则库：rules_dir 下每条规则一个 JSON 文件，CRUD 式持久化。

与每次任务上传、用完即弃的 CSV/XLSX 规则不同，这里的规则跨任务复用，
且由管理员直接声明 category/check_mode/evidence_sources 等结构化元数据，
提交合规审核时可以整体选用，不需要再靠规则文本去模糊匹配内置规则。

id 从 1000 起自增，与内置的 13 条规则（1-13）不会冲突。
"""

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from copernicus.schemas.compliance import CustomRule, CustomRuleCreate, CustomRuleUpdate

logger = logging.getLogger(__name__)

_ID_START = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, content: str) -> None:
    """先写临时文件再改名：进程崩溃不会留下损坏的规则文件（同 PersistenceService 的写入约定）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


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
        _atomic_write(self._path(rule.id), rule.model_dump_json(indent=2))
        return rule

    def update_rule(self, rule_id: int, data: CustomRuleUpdate) -> CustomRule | None:
        existing = self.get_rule(rule_id)
        if existing is None:
            return None
        changes = data.model_dump(exclude_unset=True)
        changes["updated_at"] = _now()
        updated = existing.model_copy(update=changes)
        _atomic_write(self._path(rule_id), updated.model_dump_json(indent=2))
        return updated

    def delete_rule(self, rule_id: int) -> bool:
        path = self._path(rule_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _next_id(self) -> int:
        existing = [int(f.stem) for f in self._dir.glob("*.json") if f.stem.isdigit()]
        return max(existing, default=_ID_START - 1) + 1
