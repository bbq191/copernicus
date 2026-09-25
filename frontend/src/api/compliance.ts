import client from "./client";
import { pollUntilDone } from "./polling";
import type { ComplianceResponse } from "../types/compliance";
import type { TaskSubmitResponse } from "../types/task";
import { useComplianceStore } from "../stores/complianceStore";
import type { TranscriptEntry } from "../types/transcript";

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  auditing: "合规审核中...",
};

export async function auditCompliance(
  transcriptEntries: TranscriptEntry[],
  rulesFile: File,
  parentTaskId?: string,
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
  if (parentTaskId) form.append("parent_task_id", parentTaskId);

  const { data: task } = await client.post<TaskSubmitResponse>(
    "/tasks/compliance_audit",
    form,
  );

  return pollForCompliance(task.task_id);
}

export async function persistViolationStatuses(
  taskId: string,
  updates: { violation_id: string; status: string }[],
): Promise<void> {
  await client.patch(`/tasks/${taskId}/compliance/violations`, { updates });
}

async function pollForCompliance(taskId: string): Promise<ComplianceResponse> {
  const result = await pollUntilDone(taskId, {
    statusText: STATUS_TEXT,
    failedText: "合规审核失败",
    onProgress: (percent, text) =>
      useComplianceStore.getState().setProgress(percent, text),
  });
  return result as ComplianceResponse;
}
