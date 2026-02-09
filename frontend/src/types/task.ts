import type { ComplianceResponse } from "./compliance";
import type { TranscriptionResponse, TranscriptResponse } from "./transcript";
import type { EvaluationResponse, EvaluationResult } from "./evaluation";

export type TaskStatus =
  | "pending"
  | "processing_asr"
  | "correcting"
  | "evaluating"
  | "auditing"
  | "completed"
  | "failed";

export interface TaskSubmitResponse {
  task_id: string;
  status: TaskStatus;
  existing?: boolean;
}

export interface TaskProgress {
  current_chunk: number;
  total_chunks: number;
  percent: number;
}

export interface TaskStatusResponse {
  task_id: string;
  status: TaskStatus;
  progress: TaskProgress;
  result:
    | TranscriptionResponse
    | EvaluationResponse
    | TranscriptResponse
    | ComplianceResponse
    | null;
  error: string | null;
}

export interface TaskResultsResponse {
  task_id: string;
  transcript: TranscriptResponse | null;
  evaluation: EvaluationResult | null;
  compliance: ComplianceResponse | null;
  has_audio: boolean;
}
