export interface EvaluationResult {
  formatted_content: string;
  title: string;
  /** 输入文本超过上限被截断（旧数据无此字段） */
  truncated?: boolean;
  /** Map 阶段失败、改用原文片段兜底的分块数 */
  degraded_chunks?: number;
}

export interface EvaluationResponse {
  raw_text: string;
  corrected_text: string;
  evaluation: EvaluationResult;
  processing_time_ms: number;
}
