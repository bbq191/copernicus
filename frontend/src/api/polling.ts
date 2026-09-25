import { POLL_INTERVAL_MS } from "./client";
import { getTaskStatus } from "./task";
import type { TaskStatusResponse } from "../types/task";

/** 连续失败达到该次数才放弃轮询，容忍短暂的网络抖动。 */
const MAX_CONSECUTIVE_FAILURES = 5;

type ApiError = Error & { statusCode?: number };

/** 网络中断、超时、5xx、429 属于可恢复错误；其余 4xx（如 404/422）重试无意义。 */
export function isTransientError(err: unknown): boolean {
  const code = (err as ApiError | undefined)?.statusCode;
  return code === undefined || code >= 500 || code === 429;
}

/** 记录连续失败次数，判断一次轮询失败后是否应继续重试。 */
export function createFailureGuard(max = MAX_CONSECUTIVE_FAILURES) {
  let failures = 0;
  return {
    recordSuccess() {
      failures = 0;
    },
    /** 返回 true 表示可继续重试；false 表示应放弃并向用户报错。 */
    shouldRetry(err: unknown): boolean {
      if (!isTransientError(err)) return false;
      failures += 1;
      return failures < max;
    },
  };
}

interface PollOptions {
  statusText: Record<string, string>;
  failedText: string;
  onProgress: (percent: number, text: string) => void;
}

type TaskResult = NonNullable<TaskStatusResponse["result"]>;

/** 轮询任务直到完成，返回其 result；任务失败或不可恢复错误时抛出。 */
export async function pollUntilDone(
  taskId: string,
  { statusText, failedText, onProgress }: PollOptions,
): Promise<TaskResult> {
  const guard = createFailureGuard();

  while (true) {
    let data: TaskStatusResponse;
    try {
      data = await getTaskStatus(taskId);
      guard.recordSuccess();
    } catch (err) {
      if (!guard.shouldRetry(err)) throw err;
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      continue;
    }

    if (data.status === "completed" && data.result) return data.result;
    if (data.status === "failed") throw new Error(data.error || failedText);

    onProgress(data.progress?.percent ?? 0, statusText[data.status] || "处理中...");
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}
