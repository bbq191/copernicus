import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/task", () => ({
  editTranscript: vi.fn(),
}));

import { editTranscript } from "../api/task";
import {
  discardTranscriptEdits,
  flushTranscriptEdits,
  scheduleTranscriptEdit,
} from "./transcriptPersister";
import { useToastStore } from "./toastStore";

const flush = async () => {
  await vi.advanceTimersByTimeAsync(600); // 500ms 防抖
  await vi.advanceTimersByTimeAsync(0); // 让 await 链完成
};

describe("transcriptPersister", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(editTranscript).mockReset().mockResolvedValue(undefined);
    discardTranscriptEdits();
    useToastStore.setState({ toasts: [] });
  });
  afterEach(() => vi.useRealTimers());

  it("debounces edits to the same sentence, keeping only the last", async () => {
    scheduleTranscriptEdit("task-1", { index: 0, text_corrected: "第一版" });
    scheduleTranscriptEdit("task-1", { index: 0, text_corrected: "第二版" });
    scheduleTranscriptEdit("task-1", { index: 1, text_corrected: "另一句" });
    await flush();

    expect(editTranscript).toHaveBeenCalledTimes(1);
    expect(editTranscript).toHaveBeenCalledWith(
      "task-1",
      [
        { index: 0, text_corrected: "第二版" },
        { index: 1, text_corrected: "另一句" },
      ],
      { keepalive: false },
    );
  });

  it("retries on failure and tells the user it will retry", async () => {
    vi.mocked(editTranscript).mockRejectedValueOnce(new Error("offline"));
    scheduleTranscriptEdit("task-1", { index: 0, text_corrected: "x" });
    await flush();

    expect(useToastStore.getState().toasts.at(-1)?.message).toContain("稍后将自动重试");

    vi.mocked(editTranscript).mockResolvedValueOnce(undefined);
    await vi.advanceTimersByTimeAsync(3000); // 默认重试延迟
    await vi.advanceTimersByTimeAsync(0);

    expect(editTranscript).toHaveBeenCalledTimes(2);
  });

  it("gives up after repeated failures and tells the user to act", async () => {
    vi.mocked(editTranscript).mockRejectedValue(new Error("offline"));
    scheduleTranscriptEdit("task-1", { index: 0, text_corrected: "x" });

    await flush(); // 第 1 次失败
    await vi.advanceTimersByTimeAsync(3000);
    await vi.advanceTimersByTimeAsync(0); // 重试 1
    await vi.advanceTimersByTimeAsync(6000);
    await vi.advanceTimersByTimeAsync(0); // 重试 2
    await vi.advanceTimersByTimeAsync(12_000);
    await vi.advanceTimersByTimeAsync(0); // 重试 3，达到默认上限

    expect(useToastStore.getState().toasts.at(-1)?.message).toContain("多次保存失败");
  });

  it("flush sends immediately and discard drops what is pending", async () => {
    scheduleTranscriptEdit("task-1", { index: 0, text_corrected: "x" });
    await flushTranscriptEdits({ keepalive: true });
    expect(editTranscript).toHaveBeenCalledWith(
      "task-1",
      [{ index: 0, text_corrected: "x" }],
      { keepalive: true },
    );

    scheduleTranscriptEdit("task-1", { index: 1, text_corrected: "y" });
    discardTranscriptEdits();
    await flush();
    expect(editTranscript).toHaveBeenCalledTimes(1);
  });
});
