from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# 各严重度的扣分；被人工驳回的条目不扣分
SEVERITY_PENALTY: dict[str, float] = {"high": 15.0, "medium": 8.0, "low": 3.0}


class ComplianceRule(BaseModel):
    """Single audit rule parsed from CSV/XLSX."""

    id: int
    content: str


class Violation(BaseModel):
    """Single violation detected by LLM."""

    # 报告内稳定唯一的条目标识，由 ComplianceReport 在构造时补齐
    id: str = ""
    rule_id: int
    rule_content: str
    reason: str
    severity: Literal["high", "medium", "low"] = "low"
    confidence: float
    status: Literal["pending", "confirmed", "rejected"] = "pending"

    # 音频/文本字段
    timestamp: str = ""
    timestamp_ms: int = 0
    end_ms: int = 0
    speaker: str = ""
    original_text: str = ""

    # 多源审核字段
    source: Literal["transcript", "ocr", "vision"] = "transcript"
    evidence_url: str | None = None
    evidence_text: str | None = None
    rule_ref: str | None = None

    # 认知审计（CoT 推理链）
    reasoning: str | None = None

    # 人工复核留痕
    reviewed_at: str | None = None  # 最近一次确认/驳回的 UTC 时间（ISO 8601）
    review_note: str | None = None

    def apply_review(
        self, status: Literal["pending", "confirmed", "rejected"], note: str | None = None
    ) -> None:
        """记录一次人工复核：回到待审会清空留痕，确认/驳回则写入时间与（可选）备注。"""
        self.status = status
        if status == "pending":
            self.reviewed_at = None
            self.review_note = None
            return
        self.reviewed_at = datetime.now(timezone.utc).isoformat()
        if note is not None:
            self.review_note = note.strip() or None


class ComplianceReport(BaseModel):
    """Full compliance audit report."""

    total_rules: int
    total_segments_checked: int
    total_segments: int = 0  # 转写原始句段数；大于 checked 表示文本被截断
    # 完整性标记：避免"部分审核"被误读为"无违规"
    truncated: bool = False
    total_chunks: int = 0
    failed_chunks: int = 0
    skipped_rule_ids: list[int] = Field(default_factory=list)  # 因缺少证据来源（如无 OCR 数据）而未审核的规则
    violations: list[Violation] = Field(default_factory=list)
    summary: str = ""
    compliance_score: float = 100.0
    source_counts: dict[str, int] = Field(default_factory=dict)

    def recalculate_score(self) -> float:
        """基础分 100，按严重度扣分，已驳回的条目不计入；写回并返回新分数。"""
        deduction = sum(
            SEVERITY_PENALTY[v.severity] for v in self.violations if v.status != "rejected"
        )
        self.compliance_score = max(0.0, round(100.0 - deduction, 1))
        return self.compliance_score

    @model_validator(mode="after")
    def _assign_violation_ids(self) -> "ComplianceReport":
        """为缺失 id 的违规条目按顺序补齐（同时兼容旧版持久化数据）。"""
        for i, v in enumerate(self.violations):
            if not v.id:
                v.id = f"v{i + 1:04d}"
        return self


class ComplianceResponse(BaseModel):
    """API response for compliance audit."""

    rules: list[ComplianceRule]
    report: ComplianceReport
    processing_time_ms: float


# ---------------------------------------------------------------------------
# 持久化的自定义合规规则库（CRUD 管理）
#
# category/check_mode/evidence_sources 的取值含义见 rule_registry.py 的
# RuleCategory/CheckMode；在此重复声明是为了避免 schemas 反向依赖 services。
# ---------------------------------------------------------------------------

_RuleCategory = Literal["forbidden_phrase", "behavioral", "document", "visual_check"]
_CheckMode = Literal["exact", "semantic", "visual"]
_EvidenceSource = Literal["transcript", "ocr", "vision"]
_Severity = Literal["high", "medium", "low"]


class CustomRuleBase(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000, description="审核标准原文，注入 LLM 审核 prompt")
    category: _RuleCategory
    check_mode: _CheckMode
    evidence_sources: list[_EvidenceSource] = Field(default_factory=lambda: ["transcript"])
    keywords: list[str] = Field(default_factory=list, max_length=50, description="仅 check_mode=exact 时使用")
    description: str = Field(default="", max_length=2000, description="审核说明，供 LLM 判断依据")
    severity_default: _Severity = "medium"
    enabled: bool = True


class CustomRuleCreate(CustomRuleBase):
    pass


class CustomRuleUpdate(BaseModel):
    """所有字段可选，仅更新提供的字段。"""

    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    category: _RuleCategory | None = None
    check_mode: _CheckMode | None = None
    evidence_sources: list[_EvidenceSource] | None = None
    keywords: list[str] | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    severity_default: _Severity | None = None
    enabled: bool | None = None


class CustomRule(CustomRuleBase):
    """持久化形态：固定整数 id（1000 起自增，不与内置 13 条规则冲突）+ 时间戳。"""

    id: int
    created_at: str
    updated_at: str
