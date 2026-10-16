import client, { patchKeepalive } from "./client";
import { pollUntilDone } from "./polling";
import type { PollOptions } from "./polling";
import type {
  ComplianceResponse,
  ComplianceTrends,
  TodoItem,
  ViolationStatus,
} from "../types/compliance";
import type { TaskSubmitResponse } from "../types/task";
import type { TranscriptEntry } from "../types/transcript";

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  auditing: "合规审核中...",
};

export type AuditProgress = Pick<PollOptions, "onProgress" | "signal">;

/** 规则来源：上传的 CSV/XLSX 文件，或规则库（已启用的全部自定义规则）。 */
export type RulesSource = File | "library";

export async function auditCompliance(
  transcriptEntries: TranscriptEntry[],
  rulesSource: RulesSource,
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
  if (rulesSource === "library") {
    form.append("use_rule_library", "true");
  } else {
    form.append("rules_file", rulesSource);
  }
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
  /** 省略时仅更新 assignee/due_at，不触碰复核状态 */
  status?: ViolationStatus;
  note?: string;
  /** 指派给谁复核；传空字符串清除指派，不提供（undefined）则不改动 */
  assignee?: string;
  /** 复核截止时间 ISO 8601；传空字符串清除，不提供则不改动 */
  due_at?: string;
}

/** 持久化复核结果，返回服务端按复核状态重算后的合规评分。 */
export async function persistViolationStatuses(
  taskId: string,
  updates: ViolationStatusUpdate[],
  { keepalive = false }: { keepalive?: boolean } = {},
): Promise<number> {
  const { compliance_score } = await patchKeepalive<{ compliance_score: number }>(
    `/tasks/${taskId}/compliance/violations`,
    { updates },
    keepalive,
  );
  return compliance_score;
}

export const complianceExportUrl = (taskId: string) =>
  `/api/v1/tasks/${taskId}/compliance/export`;

/** 查询指派给某人、还未处理的违规（跨任务聚合，按截止时间升序）。 */
export async function listMyTodos(assignee: string): Promise<TodoItem[]> {
  const { data } = await client.get<TodoItem[]>("/compliance/todos", {
    params: { assignee },
  });
  return data;
}

/** 跨任务聚合的合规审核趋势：命中最多的规则、严重度分布、平均合规分。 */
export async function getComplianceTrends(): Promise<ComplianceTrends> {
  const { data } = await client.get<ComplianceTrends>("/compliance/analytics/trends");
  return data;
}
