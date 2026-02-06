import client from "./client";
import type { EvaluationResult, EvaluationResponse } from "../types/evaluation";
import type { TaskSubmitResponse, TaskStatusResponse } from "../types/task";
import { useEvaluationStore } from "../stores/evaluationStore";

const POLL_INTERVAL_MS = 2000;

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  processing_asr: "语音识别中...",
  correcting: "文本纠正中...",
  evaluating: "生成摘要中...",
};

export async function evaluateText(text: string): Promise<EvaluationResult> {
  const form = new FormData();
  form.append("text", text);

  const { data: task } = await client.post<TaskSubmitResponse>(
    "/evaluate/text/async",
    form,
  );

  return pollForEvaluation(task.task_id);
}

async function pollForEvaluation(taskId: string): Promise<EvaluationResult> {
  const store = useEvaluationStore.getState;

  while (true) {
    const { data } = await client.get<TaskStatusResponse>(`/tasks/${taskId}`);

    if (data.status === "completed" && data.result) {
      const response = data.result as EvaluationResponse;
      return response.evaluation;
    }

    if (data.status === "failed") {
      throw new Error(data.error || "评估失败");
    }

    // 上报进度
    const percent = data.progress?.percent ?? 0;
    const statusText = STATUS_TEXT[data.status] || "处理中...";
    store().setProgress(percent, statusText);

    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}
