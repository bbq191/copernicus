import type { ComplianceResponse } from "./compliance";
import type { TranscriptResponse } from "./transcript";
import type { EvaluationResponse, EvaluationResult } from "./evaluation";

export type TaskStatus =
  | "pending"
  | "queued_asr"
  | "processing_asr"
  | "extracting_frames"
  | "scanning_visual"
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
  result: EvaluationResponse | TranscriptResponse | ComplianceResponse | null;
  error: string | null;
}

export interface TaskResultsResponse {
  task_id: string;
  transcript: TranscriptResponse | null;
  evaluation: EvaluationResult | null;
  compliance: ComplianceResponse | null;
  has_audio: boolean;
  has_video: boolean;
  has_synthesis: boolean;
  keyframe_count: number;
  ocr_text_count: number;
  visual_event_count: number;
}

export interface TaskSummary {
  task_id: string;
  /** 用户重命名 > 纪要标题 > 原始文件名 */
  name: string;
  filename: string;
  created_at: string;
  status: TaskStatus;
  error: string | null;
  has_video: boolean;
  has_evaluation: boolean;
  has_compliance: boolean;
}

export interface TaskListResponse {
  tasks: TaskSummary[];
  /** 磁盘上的任务总数，大于 tasks.length 表示被截断 */
  total: number;
}

export interface TranscriptTextEdit {
  index: number;
  text_corrected: string;
}
