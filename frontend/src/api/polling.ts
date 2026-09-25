import { POLL_INTERVAL_MS } from "./client";
import { isTransientError } from "./errors";
import { getTaskStatus } from "./task";
import type { TaskStatusResponse } from "../types/task";

/** 连续失败达到该次数才放弃轮询，容忍短暂的网络抖动。 */
const MAX_CONSECUTIVE_FAILURES = 5;
/** 标签页在后台时降频：用户看不到进度，没必要每 2 秒唤醒一次网络与 CPU。 */
const HIDDEN_POLL_INTERVAL_MS = 10_000;

/** 当前应使用的轮询间隔：后台时至少降到 HIDDEN_POLL_INTERVAL_MS。 */
export function pollDelayMs(base = POLL_INTERVAL_MS): number {
  return typeof document !== "undefined" && document.hidden ? Math.max(base, HIDDEN_POLL_INTERVAL_MS) : base;
}

/** 可被 AbortSignal 打断的等待；被打断时抛出 AbortError。 */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
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

export interface PollOptions {
  statusText: Record<string, string>;
  failedText: string;
  onProgress: (percent: number, text: string) => void;
  signal?: AbortSignal;
}

type TaskResult = NonNullable<TaskStatusResponse["result"]>;

/** 轮询任务直到完成，返回其 result；任务失败、不可恢复错误时抛出，signal 中止时抛出 AbortError。 */
export async function pollUntilDone(
  taskId: string,
  { statusText, failedText, onProgress, signal }: PollOptions,
): Promise<TaskResult> {
  const guard = createFailureGuard();

  while (true) {
    let data: TaskStatusResponse;
    try {
      data = await getTaskStatus(taskId);
      guard.recordSuccess();
    } catch (err) {
      if (signal?.aborted || !guard.shouldRetry(err)) throw err;
      await sleep(pollDelayMs(), signal);
      continue;
    }
    signal?.throwIfAborted();

    if (data.status === "completed" && data.result) return data.result;
    if (data.status === "failed") throw new Error(data.error || failedText);

    onProgress(data.progress?.percent ?? 0, statusText[data.status] || "处理中...");
    await sleep(pollDelayMs(), signal);
  }
}
