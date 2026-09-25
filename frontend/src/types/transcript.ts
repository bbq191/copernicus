export interface TranscriptEntry {
  timestamp: string;
  timestamp_ms: number;
  end_ms: number;
  speaker: string;
  text: string;
  text_corrected: string;
}

export interface TranscriptResponse {
  transcript: TranscriptEntry[];
  processing_time_ms: number;
  /** LLM 润色的批次统计；failed > 0 表示部分文本未经润色（旧数据无此字段） */
  correction_total_batches?: number;
  correction_failed_batches?: number;
}
