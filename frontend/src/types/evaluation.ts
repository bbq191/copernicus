export interface EvaluationMeta {
  title: string;
  category: string;
  keywords: string[];
}

export interface EvaluationScores {
  logic: number;
  info_density: number;
  expression: number;
  total: number;
}

export interface EvaluationAnalysis {
  main_points: string[];
  key_data: string[];
  sentiment: string;
}

export interface EvaluationResult {
  meta: EvaluationMeta;
  scores: EvaluationScores;
  analysis: EvaluationAnalysis;
  summary: string;
}

export interface EvaluationResponse {
  raw_text: string;
  corrected_text: string;
  evaluation: EvaluationResult;
  processing_time_ms: number;
}
