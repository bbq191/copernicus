export interface SegmentSchema {
  text: string;
  start_ms: number;
  end_ms: number;
  confidence: number;
}

export interface TranscriptEntry {
  timestamp: string;
  timestamp_ms: number;
  speaker: string;
  text: string;
  text_corrected: string;
}

export interface TranscriptResponse {
  transcript: TranscriptEntry[];
  processing_time_ms: number;
}

export interface TranscriptionResponse {
  raw_text: string;
  corrected_text: string;
  segments: SegmentSchema[];
  processing_time_ms: number;
}

export interface HealthResponse {
  asr_loaded: boolean;
  llm_reachable: boolean;
}
