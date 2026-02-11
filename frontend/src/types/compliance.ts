export interface ComplianceRule {
  id: number;
  content: string;
}

export type ViolationStatus = "pending" | "confirmed" | "rejected";
export type ViolationSource = "transcript" | "ocr" | "vision";

export interface Violation {
  // 通用
  rule_id: number;
  rule_content: string;
  reason: string;
  severity: "high" | "medium" | "low";
  confidence: number;
  status: ViolationStatus;

  // 违规来源
  source: ViolationSource;

  // 证据
  evidence_url: string | null;
  evidence_text: string | null;
  rule_ref: string | null;

  // 认知审计推理链
  reasoning?: string;

  // 音频/文本
  timestamp: string;
  timestamp_ms: number;
  end_ms: number;
  speaker: string;
  original_text: string;
}

export interface EvidenceItem {
  type: "screenshot" | "ocr_text" | "audio_clip";
  url: string;
  description: string;
  timestamp_ms: number;
}

export interface ComplianceReport {
  total_rules: number;
  total_segments_checked: number;
  violations: Violation[];
  summary: string;
  compliance_score: number;
}

export interface ComplianceResponse {
  rules: ComplianceRule[];
  report: ComplianceReport;
  processing_time_ms: number;
}
