import { useEffect, useRef } from "react";
import { isAbortError, pollDelayMs, sleep } from "../api/polling";

/**
 * 通用轮询：enabled 为 true 期间循环调用 tick，直到 tick 返回 true 或组件卸载。
 *
 * - 上一次 tick 结束后才计划下一次，请求不会堆积
 * - 标签页在后台时自动降频
 * - 卸载/关闭时打断等待；在途 tick 的结果由调用方通过 signal.aborted 判断是否丢弃
 * tick 里抛出的异常会被吞掉并在下个周期重试，需要放弃时请自行返回 true。
 */
export function usePolling(
  tick: (signal: AbortSignal) => Promise<boolean | void>,
  { enabled, intervalMs }: { enabled: boolean; intervalMs?: number },
) {
  // 始终调用最新的 tick，避免闭包捕获过期状态，又不用把它放进 effect 依赖
  const tickRef = useRef(tick);
  useEffect(() => {
    tickRef.current = tick;
  });

  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    const { signal } = abort;

    void (async () => {
      try {
        while (!signal.aborted) {
          let done = false;
          try {
            done = (await tickRef.current(signal)) === true;
          } catch {
            // 可恢复错误：下个周期重试
          }
          if (done || signal.aborted) return;
          await sleep(pollDelayMs(intervalMs), signal);
        }
      } catch (err) {
        if (!isAbortError(err)) throw err;
      }
    })();

    return () => abort.abort();
  }, [enabled, intervalMs]);
}
