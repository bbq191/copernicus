import type { TranscriptionResponse, TranscriptResponse } from "./transcript";
import type { EvaluationResponse } from "./evaluation";

export type TaskStatus =
  | "pending"
  | "processing_asr"
  | "correcting"
  | "evaluating"
  | "completed"
  | "failed";

export interface TaskSubmitResponse {
  task_id: string;
  status: TaskStatus;
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
  result: TranscriptionResponse | EvaluationResponse | TranscriptResponse | null;
  error: string | null;
}
