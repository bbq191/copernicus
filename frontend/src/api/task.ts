import client from "./client";
import type {
  TaskSubmitResponse,
  TaskStatusResponse,
  TaskResultsResponse,
} from "../types/task";

export async function submitTranscriptTask(
  file: File,
  hotwords?: string,
): Promise<TaskSubmitResponse> {
  const form = new FormData();
  form.append("file", file);
  if (hotwords) form.append("hotwords", hotwords);
  const { data } = await client.post<TaskSubmitResponse>(
    "/tasks/transcript",
    form,
  );
  return data;
}

export async function getTaskStatus(
  taskId: string,
): Promise<TaskStatusResponse> {
  const { data } = await client.get<TaskStatusResponse>(`/tasks/${taskId}`);
  return data;
}

export async function getTaskResults(
  taskId: string,
): Promise<TaskResultsResponse> {
  const { data } = await client.get<TaskResultsResponse>(
    `/tasks/${taskId}/results`,
  );
  return data;
}

export async function rerunTranscript(
  taskId: string,
): Promise<TaskSubmitResponse> {
  const { data } = await client.post<TaskSubmitResponse>(
    `/tasks/${taskId}/rerun-transcript`,
  );
  return data;
}

export async function rerunEvaluation(
  taskId: string,
): Promise<TaskSubmitResponse> {
  const { data } = await client.post<TaskSubmitResponse>(
    `/tasks/${taskId}/rerun-evaluation`,
  );
  return data;
}

export function getTaskMediaUrl(taskId: string): string {
  return `/api/v1/tasks/${taskId}/media`;
}

export function getFrameUrl(taskId: string, filename: string): string {
  return `/api/v1/tasks/${taskId}/frames/${filename}`;
}

/**
 * 将 evidence_url 解析为可访问的 HTTP URL。
 * 兼容：纯 filename / 绝对文件路径（旧数据） / 已有 API 路径。
 */
export function resolveEvidenceUrl(
  evidenceUrl: string | null | undefined,
  taskId: string | null,
): string | null {
  if (!evidenceUrl || !taskId) return null;
  if (evidenceUrl.startsWith("http") || evidenceUrl.startsWith("/api"))
    return evidenceUrl;
  // 提取 filename：兼容 Windows 反斜杠和 Unix 正斜杠
  const filename = evidenceUrl.includes("/") || evidenceUrl.includes("\\")
    ? evidenceUrl.split(/[/\\]/).pop()!
    : evidenceUrl;
  return getFrameUrl(taskId, filename);
}
