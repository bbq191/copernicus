import type { ComplianceReport, Violation, ViolationSource } from "../types/compliance";

export type SeverityFilter = "all" | "high" | "medium" | "low";
export type StatusFilter = "all" | "pending" | "confirmed" | "rejected";
export type SourceFilter = "all" | ViolationSource;

export interface ViolationFilters {
  severity: SeverityFilter;
  status: StatusFilter;
  source: SourceFilter;
  query: string;
}

export function filterViolations(violations: Violation[], f: ViolationFilters): Violation[] {
  const q = f.query.trim().toLowerCase();
  return violations.filter(
    (v) =>
      (f.severity === "all" || v.severity === f.severity) &&
      (f.status === "all" || v.status === f.status) &&
      (f.source === "all" || v.source === f.source) &&
      (!q ||
        v.reason.toLowerCase().includes(q) ||
        v.original_text.toLowerCase().includes(q) ||
        v.rule_content.toLowerCase().includes(q) ||
        (v.evidence_text?.toLowerCase().includes(q) ?? false)),
  );
}

export interface ViolationSummary {
  total: number;
  severity: Record<"high" | "medium" | "low", number>;
  source: Record<ViolationSource, number>;
  status: Record<"pending" | "confirmed" | "rejected", number>;
}

/** 一次遍历统计各维度数量，供筛选按钮与概览卡片共用。 */
export function summarizeViolations(report: ComplianceReport | null): ViolationSummary {
  const summary: ViolationSummary = {
    total: 0,
    severity: { high: 0, medium: 0, low: 0 },
    source: { transcript: 0, ocr: 0, vision: 0 },
    status: { pending: 0, confirmed: 0, rejected: 0 },
  };
  for (const v of report?.violations ?? []) {
    summary.total += 1;
    if (v.severity in summary.severity) summary.severity[v.severity] += 1;
    if (v.source in summary.source) summary.source[v.source] += 1;
    if (v.status in summary.status) summary.status[v.status] += 1;
  }
  return summary;
}

export interface ScoreLevel {
  text: "text-success" | "text-warning" | "text-error";
  badge: "badge-success" | "badge-warning" | "badge-error";
  label: string;
}

/** 合规分数分档：≥80 良好，≥60 需关注，其余高风险。各处的颜色与文案共用这一处阈值。 */
export function scoreLevel(score: number): ScoreLevel {
  if (score >= 80) return { text: "text-success", badge: "badge-success", label: "良好" };
  if (score >= 60) return { text: "text-warning", badge: "badge-warning", label: "需关注" };
  return { text: "text-error", badge: "badge-error", label: "高风险" };
}
