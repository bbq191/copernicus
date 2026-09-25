import client from "./client";
import { pollUntilDone } from "./polling";
import type { PollOptions } from "./polling";
import type { EvaluationResult, EvaluationResponse } from "../types/evaluation";
import type { TaskSubmitResponse } from "../types/task";

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  queued_asr: "排队等待语音识别...",
  processing_asr: "语音识别中...",
  correcting: "文本纠正中...",
  evaluating: "生成摘要中...",
};

export type EvaluationProgress = Pick<PollOptions, "onProgress" | "signal">;

export async function evaluateText(
  text: string,
  parentTaskId: string | undefined,
  templateId: string,
  { onProgress, signal }: EvaluationProgress,
): Promise<EvaluationResult> {
  const form = new FormData();
  form.append("text", text);
  form.append("template_id", templateId);
  if (parentTaskId) form.append("parent_task_id", parentTaskId);

  const { data: task } = await client.post<TaskSubmitResponse>("/evaluate/text/async", form, { signal });

  const result = await pollUntilDone(task.task_id, {
    statusText: STATUS_TEXT,
    failedText: "评估失败",
    onProgress,
    signal,
  });
  return (result as EvaluationResponse).evaluation;
}
