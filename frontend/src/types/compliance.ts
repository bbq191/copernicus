export interface ComplianceRule {
  id: number;
  content: string;
}

export type ViolationStatus = "pending" | "confirmed" | "rejected";
export type ViolationSource = "transcript" | "ocr" | "vision";

export interface Violation {
  /** 报告内稳定唯一的标识，用于选择与状态持久化 */
  id: string;

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

  // 人工复核留痕（旧数据可能缺失）
  reviewed_at?: string | null;
  review_note?: string | null;

  // 复核分配：自由文本姓名，不依赖账户体系
  assignee: string | null;
  due_at: string | null;

  // 音频/文本
  timestamp: string;
  timestamp_ms: number;
  end_ms: number;
  speaker: string;
  original_text: string;
}

export interface ComplianceReport {
  total_rules: number;
  total_segments_checked: number;
  /** 转写原始句段数，大于已检查数表示文本被截断（旧数据无此字段） */
  total_segments?: number;
  truncated?: boolean;
  total_chunks?: number;
  failed_chunks?: number;
  /** 因缺少证据来源（如无 OCR 数据）而未审核的规则 id */
  skipped_rule_ids?: number[];
  violations: Violation[];
  summary: string;
  compliance_score: number;
}

export interface ComplianceResponse {
  rules: ComplianceRule[];
  report: ComplianceReport;
  processing_time_ms: number;
}

/** "我的待办"列表的一项：跨任务聚合的违规条目，多带一个 task_id 用于跳转。 */
export interface TodoItem extends Violation {
  task_id: string;
}

export interface ComplianceTrendRule {
  rule_id: number;
  rule_content: string;
  /** 命中次数，不含已驳回（人工确认误报）的条目 */
  count: number;
}

export interface ComplianceTrends {
  total_tasks: number;
  avg_compliance_score: number | null;
  top_rules: ComplianceTrendRule[];
  severity_counts: Partial<Record<"high" | "medium" | "low", number>>;
}
