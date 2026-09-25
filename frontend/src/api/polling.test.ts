import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TaskStatusResponse } from "../types/task";

vi.mock("./task", () => ({ getTaskStatus: vi.fn() }));

import { getTaskStatus } from "./task";
import { createFailureGuard, isTransientError, pollUntilDone } from "./polling";

const apiError = (statusCode?: number) =>
  Object.assign(new Error("boom"), { statusCode });

const status = (over: Partial<TaskStatusResponse>): TaskStatusResponse => ({
  task_id: "t",
  status: "pending",
  progress: { current_chunk: 0, total_chunks: 0, percent: 0 },
  result: null,
  error: null,
  ...over,
});

describe("isTransientError", () => {
  it.each([undefined, 500, 502, 503, 429])("treats %s as recoverable", (code) => {
    expect(isTransientError(apiError(code))).toBe(true);
  });

  it.each([400, 404, 409, 422])("treats %s as fatal", (code) => {
    expect(isTransientError(apiError(code))).toBe(false);
  });
});

describe("createFailureGuard", () => {
  it("gives up only after N consecutive failures", () => {
    const guard = createFailureGuard(3);
    expect(guard.shouldRetry(apiError())).toBe(true);
    expect(guard.shouldRetry(apiError())).toBe(true);
    expect(guard.shouldRetry(apiError())).toBe(false);
  });

  it("resets the counter on success", () => {
    const guard = createFailureGuard(3);
    guard.shouldRetry(apiError());
    guard.shouldRetry(apiError());
    guard.recordSuccess();
    expect(guard.shouldRetry(apiError())).toBe(true);
    expect(guard.shouldRetry(apiError())).toBe(true);
  });

  it("never retries a fatal error", () => {
    expect(createFailureGuard(10).shouldRetry(apiError(404))).toBe(false);
  });
});

describe("pollUntilDone", () => {
  const opts = () => ({ statusText: { pending: "排队中" }, failedText: "失败", onProgress: vi.fn() });

  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(getTaskStatus).mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("survives transient errors and returns the result", async () => {
    const result = { transcript: [], processing_time_ms: 1 };
    vi.mocked(getTaskStatus)
      .mockRejectedValueOnce(apiError())
      .mockRejectedValueOnce(apiError(503))
      .mockResolvedValueOnce(status({ status: "completed", result }));

    const promise = pollUntilDone("t", opts());
    await vi.runAllTimersAsync();

    await expect(promise).resolves.toBe(result);
    expect(getTaskStatus).toHaveBeenCalledTimes(3);
  });

  it("aborts immediately on a fatal error", async () => {
    vi.mocked(getTaskStatus).mockRejectedValue(apiError(404));
    await expect(pollUntilDone("t", opts())).rejects.toThrow("boom");
    expect(getTaskStatus).toHaveBeenCalledTimes(1);
  });

  it("gives up after too many consecutive transient failures", async () => {
    vi.mocked(getTaskStatus).mockRejectedValue(apiError());
    const promise = pollUntilDone("t", opts());
    const assertion = expect(promise).rejects.toThrow("boom");
    await vi.runAllTimersAsync();
    await assertion;
    expect(getTaskStatus).toHaveBeenCalledTimes(5);
  });

  it("throws the server error message when the task failed", async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(status({ status: "failed", error: "模型崩溃" }));
    await expect(pollUntilDone("t", opts())).rejects.toThrow("模型崩溃");
  });

  it("falls back to the default message when a failed task has no error", async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(status({ status: "failed" }));
    await expect(pollUntilDone("t", opts())).rejects.toThrow("失败");
  });

  it("reports progress with mapped status text while waiting", async () => {
    const o = opts();
    vi.mocked(getTaskStatus)
      .mockResolvedValueOnce(status({ progress: { current_chunk: 1, total_chunks: 4, percent: 25 } }))
      .mockResolvedValueOnce(status({ status: "completed", result: { transcript: [], processing_time_ms: 1 } }));

    const promise = pollUntilDone("t", o);
    await vi.runAllTimersAsync();
    await promise;

    expect(o.onProgress).toHaveBeenCalledWith(25, "排队中");
  });
});
