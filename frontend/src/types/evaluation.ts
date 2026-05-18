export interface EvaluationResult {
  formatted_content: string;
  title: string;
}

export interface EvaluationResponse {
  raw_text: string;
  corrected_text: string;
  evaluation: EvaluationResult;
  processing_time_ms: number;
}
