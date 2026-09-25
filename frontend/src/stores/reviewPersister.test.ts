import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewPersister } from "./reviewPersister";
import type { ReviewPersisterDeps } from "./reviewPersister";

const update = (id: string, status = "confirmed") => ({ violation_id: id, status });

function setup(over: Partial<ReviewPersisterDeps> = {}) {
  const send = vi.fn<ReviewPersisterDeps["send"]>().mockResolvedValue(88);
  const onSaved = vi.fn();
  const onError = vi.fn();
  const persister = new ReviewPersister({ send, onSaved, onError, retryDelayMs: 1000, ...over });
  return { persister, send, onSaved, onError };
}

describe("ReviewPersister", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces changes inside the debounce window into one request", async () => {
    const { persister, send, onSaved } = setup();
    persister.schedule("t1", update("a"));
    persister.schedule("t1", update("b"));
    persister.schedule("t1", update("a", "rejected")); // 同一违规只保留最后一次

    await vi.advanceTimersByTimeAsync(600);

    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("t1", [update("a", "rejected"), update("b")], { keepalive: false });
    expect(onSaved).toHaveBeenCalledWith("t1", 88);
  });

  it("binds updates to the task they were made on when the task changes mid-window", async () => {
    const { persister, send } = setup();
    persister.schedule("t1", update("a"));
    persister.schedule("t2", update("x")); // 切换任务：t1 的修改先行提交

    await vi.advanceTimersByTimeAsync(600);

    expect(send.mock.calls.map((c) => c[0])).toEqual(["t1", "t2"]);
    expect(send.mock.calls[0][1]).toEqual([update("a")]);
    expect(send.mock.calls[1][1]).toEqual([update("x")]);
  });

  it("puts a failed batch back and retries with backoff, without overwriting newer changes", async () => {
    const { persister, send, onError, onSaved } = setup();
    send.mockRejectedValueOnce(new Error("offline"));

    persister.schedule("t1", update("a", "confirmed"));
    await vi.advanceTimersByTimeAsync(600);
    expect(onError).toHaveBeenCalledWith(true);

    persister.schedule("t1", update("a", "rejected")); // 失败期间的新修改优先
    await vi.advanceTimersByTimeAsync(600);
    expect(send).toHaveBeenLastCalledWith("t1", [update("a", "rejected")], { keepalive: false });
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("stops retrying after maxRetries and reports it", async () => {
    const { persister, send, onError } = setup({ maxRetries: 2 });
    send.mockRejectedValue(new Error("offline"));

    persister.schedule("t1", update("a"));
    await vi.advanceTimersByTimeAsync(600); // 第 1 次失败
    await vi.advanceTimersByTimeAsync(1000); // 重试 1
    await vi.advanceTimersByTimeAsync(2000); // 重试 2
    await vi.advanceTimersByTimeAsync(10_000);

    expect(send).toHaveBeenCalledTimes(3);
    expect(onError).toHaveBeenLastCalledWith(false);
  });

  it("serializes requests so an older score never overwrites a newer one", async () => {
    const order: string[] = [];
    let release!: () => void;
    const { persister, send } = setup({
      onSaved: (_t, score) => order.push(`saved:${score}`),
    });
    send.mockImplementationOnce(() => new Promise((res) => (release = () => res(70))));
    send.mockResolvedValueOnce(95);

    persister.schedule("t1", update("a"));
    await vi.advanceTimersByTimeAsync(600); // 第 1 个请求挂起
    persister.schedule("t1", update("b"));
    await vi.advanceTimersByTimeAsync(600); // 第 2 个请求必须等第 1 个
    expect(send).toHaveBeenCalledTimes(1);

    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(order).toEqual(["saved:70", "saved:95"]);
  });

  it("flush sends immediately and discard drops what is pending", async () => {
    const { persister, send } = setup();
    persister.schedule("t1", update("a"));
    await persister.flush({ keepalive: true });
    expect(send).toHaveBeenCalledWith("t1", [update("a")], { keepalive: true });

    persister.schedule("t1", update("b"));
    persister.discard();
    await vi.advanceTimersByTimeAsync(600);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
