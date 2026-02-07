import client from "./client";
import type { ComplianceResponse } from "../types/compliance";
import type { TaskSubmitResponse, TaskStatusResponse } from "../types/task";
import { useComplianceStore } from "../stores/complianceStore";
import type { TranscriptEntry } from "../types/transcript";

const POLL_INTERVAL_MS = 2000;

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  auditing: "合规审核中...",
};

export async function auditCompliance(
  transcriptEntries: TranscriptEntry[],
  rulesFile: File,
): Promise<ComplianceResponse> {
  const transcript = JSON.stringify(
    transcriptEntries.map((e) => ({
      timestamp: e.timestamp,
      timestamp_ms: e.timestamp_ms,
      speaker: e.speaker,
      text_corrected: e.text_corrected,
    })),
  );

  const form = new FormData();
  form.append("transcript", transcript);
  form.append("rules_file", rulesFile);

  const { data: task } = await client.post<TaskSubmitResponse>(
    "/compliance/audit/async",
    form,
  );

  return pollForCompliance(task.task_id);
}

async function pollForCompliance(taskId: string): Promise<ComplianceResponse> {
  const store = useComplianceStore.getState;

  while (true) {
    const { data } = await client.get<TaskStatusResponse>(`/tasks/${taskId}`);

    if (data.status === "completed" && data.result) {
      return data.result as ComplianceResponse;
    }

    if (data.status === "failed") {
      throw new Error(data.error || "合规审核失败");
    }

    const percent = data.progress?.percent ?? 0;
    const statusText = STATUS_TEXT[data.status] || "处理中...";
    store().setProgress(percent, statusText);

    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}
