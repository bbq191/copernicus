import type { ComplianceReport } from "../types/compliance";
import type { EvaluationResult } from "../types/evaluation";

/** 转写的完整性提示：LLM 润色失败的批次只做了规则/词典处理。 */
export function transcriptIncompleteness(correction: { total: number; failed: number }): string[] {
  if (!correction.failed) return [];
  return [
    `${correction.failed} / ${correction.total} 批文本的 LLM 润色失败，这些内容保留了识别原文，可能含口语、重复或错别字`,
  ];
}

/** 审核报告的完整性提示；返回空数组表示结果完整。 */
export function reportIncompleteness(report: ComplianceReport): string[] {
  const notes: string[] = [];
  if (report.truncated && report.total_segments) {
    notes.push(
      `文本超过审核上限，仅检查了前 ${report.total_segments_checked} / ${report.total_segments} 个段落，其余内容未审核`,
    );
  }
  if (report.skipped_rule_ids?.length) {
    notes.push(
      `${report.skipped_rule_ids.length} 条规则依赖屏幕文字（OCR），本任务没有 OCR 数据，这些规则未被审核（规则 ${report.skipped_rule_ids.join("、")}）`,
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
