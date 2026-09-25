import type { ComplianceReport } from "../types/compliance";
import type { EvaluationResult } from "../types/evaluation";

/** 审核报告的完整性提示；返回空数组表示结果完整。 */
export function reportIncompleteness(report: ComplianceReport): string[] {
  const notes: string[] = [];
  if (report.truncated && report.total_segments) {
    notes.push(
      `文本超过审核上限，仅检查了前 ${report.total_segments_checked} / ${report.total_segments} 个段落，其余内容未审核`,
    );
  }
  if (report.failed_chunks) {
    notes.push(
      `${report.failed_chunks} / ${report.total_chunks ?? "?"} 个审核分块因模型调用失败被跳过，结果可能存在漏检`,
    );
  }
  return notes;
}

/** 会议纪要的完整性提示；返回空数组表示结果完整。 */
export function evaluationIncompleteness(evaluation: EvaluationResult): string[] {
  const notes: string[] = [];
  if (evaluation.truncated) {
    notes.push("文本超过纪要生成上限，后半部分内容未纳入纪要");
  }
  if (evaluation.degraded_chunks) {
    notes.push(
      `${evaluation.degraded_chunks} 个片段的要点提炼失败，已改用原文片段代替，纪要可能不完整`,
    );
  }
  return notes;
}
