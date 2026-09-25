import client from "./client";
import { pollUntilDone } from "./polling";
import type { PollOptions } from "./polling";
import type { ComplianceResponse } from "../types/compliance";
import type { TaskSubmitResponse } from "../types/task";
import type { TranscriptEntry } from "../types/transcript";

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  auditing: "合规审核中...",
};

export type AuditProgress = Pick<PollOptions, "onProgress" | "signal">;

export async function auditCompliance(
  transcriptEntries: TranscriptEntry[],
  rulesFile: File,
  parentTaskId: string | undefined,
  { onProgress, signal }: AuditProgress,
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

  const { data: task } = await client.post<TaskSubmitResponse>("/tasks/compliance_audit", form, { signal });

  const result = await pollUntilDone(task.task_id, {
    statusText: STATUS_TEXT,
    failedText: "合规审核失败",
    onProgress,
    signal,
  });
  return result as ComplianceResponse;
}

export interface ViolationStatusUpdate {
  violation_id: string;
  status: string;
  note?: string;
}

/**
 * 持久化复核结果，返回服务端按复核状态重算后的合规评分。
 * keepalive 用于页面关闭前的最后一次提交：axios 不支持，改用 fetch，浏览器会在页面卸载后继续发送。
 */
export async function persistViolationStatuses(
  taskId: string,
  updates: ViolationStatusUpdate[],
  { keepalive = false }: { keepalive?: boolean } = {},
): Promise<number> {
  const url = `/tasks/${taskId}/compliance/violations`;
  if (!keepalive) {
    const { data } = await client.patch<{ compliance_score: number }>(url, { updates });
    return data.compliance_score;
  }
  const res = await fetch(`${client.defaults.baseURL}${url}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates }),
    keepalive: true,
  });
  if (!res.ok) throw new Error(`保存失败（${res.status}）`);
  return ((await res.json()) as { compliance_score: number }).compliance_score;
}

export const complianceExportUrl = (taskId: string) =>
  `/api/v1/tasks/${taskId}/compliance/export`;
