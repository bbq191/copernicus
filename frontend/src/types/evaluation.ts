export interface ActionItem {
  task: string;
  owner: string;
  due: string;
  /** 在转写中定位到的位置（毫秒）；null 表示没能定位 */
  timestamp_ms: number | null;
}

export interface Decision {
  content: string;
  timestamp_ms: number | null;
}

/** ok 全部成功；partial 部分分块失败；failed 提取失败；skipped 未启用（旧数据无此字段） */
export type StructureStatus = "ok" | "partial" | "failed" | "skipped";

export interface EvaluationResult {
  formatted_content: string;
  title: string;
  /** 输入文本超过上限被截断（旧数据无此字段） */
  truncated?: boolean;
  /** Map 阶段失败、改用原文片段兜底的分块数 */
  degraded_chunks?: number;
  action_items?: ActionItem[];
  decisions?: Decision[];
  structure_status?: StructureStatus;
}

export interface EvaluationResponse {
  raw_text: string;
  corrected_text: string;
  evaluation: EvaluationResult;
  processing_time_ms: number;
}
