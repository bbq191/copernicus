from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class ComplianceReport(BaseModel):
    """Full compliance audit report."""

    total_rules: int
    total_segments_checked: int
    total_segments: int = 0  # 转写原始句段数；大于 checked 表示文本被截断
    # 完整性标记：避免"部分审核"被误读为"无违规"
    truncated: bool = False
    total_chunks: int = 0
    failed_chunks: int = 0
    violations: list[Violation] = Field(default_factory=list)
    summary: str = ""
    compliance_score: float = 100.0
    source_counts: dict[str, int] = Field(default_factory=dict)

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
