import client from "./client";
import { pollUntilDone } from "./polling";
import type { EvaluationResult, EvaluationResponse } from "../types/evaluation";
import type { TaskSubmitResponse } from "../types/task";
import { useEvaluationStore } from "../stores/evaluationStore";

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  processing_asr: "语音识别中...",
  correcting: "文本纠正中...",
  evaluating: "生成摘要中...",
};

export async function evaluateText(
  text: string,
  parentTaskId?: string,
  templateId = "universal",
): Promise<EvaluationResult> {
  const form = new FormData();
  form.append("text", text);
  form.append("template_id", templateId);
  if (parentTaskId) form.append("parent_task_id", parentTaskId);

  const { data: task } = await client.post<TaskSubmitResponse>(
    "/evaluate/text/async",
    form,
  );

  return pollForEvaluation(task.task_id);
}

async function pollForEvaluation(taskId: string): Promise<EvaluationResult> {
  const result = await pollUntilDone(taskId, {
    statusText: STATUS_TEXT,
    failedText: "评估失败",
    onProgress: (percent, text) =>
      useEvaluationStore.getState().setProgress(percent, text),
  });
  return (result as EvaluationResponse).evaluation;
}
