import { useEffect } from "react";
import { getTaskStatus, getTaskResults } from "../api/task";
import { errorMessage } from "../api/errors";
import { createFailureGuard, isAbortError, pollDelayMs, sleep } from "../api/polling";
import { hydrateWorkspace } from "../stores/hydrateWorkspace";
import { useTaskStore } from "../stores/taskStore";
import { useTranscriptStore } from "../stores/transcriptStore";
import type { TaskStatusResponse } from "../types/task";
import type { TranscriptResponse } from "../types/transcript";

/** 任务完成：先加载持久化结果，再把状态置为 completed，保证面板挂载时数据已就绪。 */
async function applyCompleted(taskId: string, res: TaskStatusResponse, signal: AbortSignal) {
  let restored = false;
  try {
    const results = await getTaskResults(taskId);
    if (signal.aborted) return;
    restored = hydrateWorkspace(taskId, results);
  } catch {
    // 结果读取失败不影响转写展示，退回到状态响应里携带的转写
  }
  if (!restored) {
    const transcript = res.result as TranscriptResponse | undefined;
    if (transcript && "transcript" in transcript) {
      useTranscriptStore.getState().setRawEntries(transcript.transcript);
    }
  }
  useTaskStore.getState().updateStatus("completed", res.progress);
}

async function pollTask(taskId: string, signal: AbortSignal) {
  const { updateStatus, setError } = useTaskStore.getState();
  const guard = createFailureGuard();

  try {
    while (!signal.aborted) {
      try {
        const res = await getTaskStatus(taskId);
        if (signal.aborted) return;
        guard.recordSuccess();

        if (res.status === "completed" && res.result) {
          await applyCompleted(taskId, res, signal);
          return;
        }
        if (res.status === "failed") {
          setError(res.error ?? "任务失败");
          return;
        }
        updateStatus(res.status, res.progress);
      } catch (err) {
        if (signal.aborted) return;
        // 网络抖动等可恢复错误：下个周期重试；连续失败或不可恢复才报错
        if (!guard.shouldRetry(err)) {
          setError(errorMessage(err, "轮询失败"));
          return;
        }
      }
      await sleep(pollDelayMs(), signal);
    }
  } catch (err) {
    if (!isAbortError(err)) throw err;
  }
}

/**
 * 轮询当前任务直到完成或失败。
 * effect 只依赖 taskId 与"是否已结束"，中间的状态迁移不会重启轮询；
 * 卸载或切换任务时通过 AbortSignal 终止，在途请求的结果会被丢弃。
 */
export function useTaskPolling(enabled = true) {
  const taskId = useTaskStore((s) => s.taskId);
  const finished = useTaskStore((s) => s.status === "completed" || s.status === "failed");

  useEffect(() => {
    if (!enabled || !taskId || finished) return;
    const abort = new AbortController();
    void pollTask(taskId, abort.signal);
    return () => abort.abort();
  }, [enabled, taskId, finished]);
}
