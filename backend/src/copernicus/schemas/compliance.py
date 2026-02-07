from pydantic import BaseModel, Field


class ComplianceRule(BaseModel):
    """Single audit rule parsed from CSV/XLSX."""

    id: int
    content: str


class Violation(BaseModel):
    """Single violation detected by LLM."""

    rule_id: int
    rule_content: str
    timestamp: str
    timestamp_ms: int
    end_ms: int
    speaker: str
    original_text: str
    reason: str
    severity: str  # "high" | "medium" | "low"
    confidence: float


class ComplianceReport(BaseModel):
    """Full compliance audit report."""

    total_rules: int
    total_segments_checked: int
    violations: list[Violation] = Field(default_factory=list)
    summary: str = ""
    compliance_score: float = 100.0


class ComplianceResponse(BaseModel):
    """API response for compliance audit."""

    rules: list[ComplianceRule]
    report: ComplianceReport
    processing_time_ms: float
