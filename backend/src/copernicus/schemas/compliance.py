from typing import Literal

from pydantic import BaseModel, Field


class ComplianceRule(BaseModel):
    """Single audit rule parsed from CSV/XLSX."""

    id: int
    content: str


class Violation(BaseModel):
    """Single violation detected by LLM."""

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
    violations: list[Violation] = Field(default_factory=list)
    summary: str = ""
    compliance_score: float = 100.0
    source_counts: dict[str, int] = Field(default_factory=dict)


class ComplianceResponse(BaseModel):
    """API response for compliance audit."""

    rules: list[ComplianceRule]
    report: ComplianceReport
    processing_time_ms: float
