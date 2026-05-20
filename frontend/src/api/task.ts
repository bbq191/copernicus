import client, { taskMediaUrl, taskFrameUrl } from "./client";
import { computeFileSHA256 } from "../utils/fileHash";
import { chunkedUploadFile } from "../utils/chunkedUpload";
import type {
  TaskSubmitResponse,
  TaskStatusResponse,
  TaskResultsResponse,
} from "../types/task";

// 大于此阈值使用分片上传（断点续传），小于此阈值使用普通上传（带重试）
const CHUNKED_THRESHOLD = 20 * 1024 * 1024; // 20 MB
const UPLOAD_MAX_RETRIES = 3;

export interface SubmitOptions {
  onProgress?: (received: number, total: number) => void;
  templateId?: string;
}

function isRetryable(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const statusCode = (err as Error & { statusCode?: number }).statusCode;
  return statusCode === undefined || statusCode >= 500;
}

async function uploadWithRetry(form: FormData): Promise<TaskSubmitResponse> {
  let lastError: Error = new Error("上传失败");
  for (let attempt = 0; attempt < UPLOAD_MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, 2 ** attempt * 1000));
    }
    try {
      const { data } = await client.post<TaskSubmitResponse>(
        "/tasks/standard_minutes",
        form,
      );
      return data;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      if (!isRetryable(err)) throw err;
    }
  }
  throw lastError;
}

export async function submitStandardMinutesTask(
  file: File,
  hotwords?: string,
  visualScan?: boolean,
  options?: SubmitOptions,
): Promise<TaskSubmitResponse> {
  const hash = await computeFileSHA256(file);

  // 大文件：分片上传（断点续传）
  // 注：分片路径服务端固定使用 universal 模板，完成后可在摘要面板切换重新评估
  if (file.size >= CHUNKED_THRESHOLD) {
    return chunkedUploadFile(file, hash, {
      hotwords,
      visualScan,
      onProgress: options?.onProgress,
    });
  }

  // 小文件：预检（跳过重复上传）+ 普通上传
  try {
    const { data } = await client.get<TaskSubmitResponse>(
      `/tasks/lookup?hash=${hash}`,
    );
    return data;
  } catch {
    // 404 = not found, proceed with upload
  }

  const form = new FormData();
  form.append("file", file);
  if (hotwords) form.append("hotwords", hotwords);
  if (visualScan) form.append("visual_scan", "true");
  form.append("template_id", options?.templateId ?? "universal");

  return uploadWithRetry(form);
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


export function getTaskMediaUrl(taskId: string): string {
  return taskMediaUrl(taskId);
}

export function getFrameUrl(taskId: string, filename: string): string {
  return taskFrameUrl(taskId, filename);
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
  const filename = evidenceUrl.includes("/") || evidenceUrl.includes("\\")
    ? evidenceUrl.split(/[/\\]/).pop()!
    : evidenceUrl;
  return getFrameUrl(taskId, filename);
}
