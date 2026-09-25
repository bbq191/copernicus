import type { ViolationStatusUpdate } from "../api/compliance";

export interface SendOptions {
  /** 页面即将关闭时使用，请求在页面卸载后仍会被浏览器发完 */
  keepalive: boolean;
}

export interface ReviewPersisterDeps {
  /** 提交一批复核结果，返回服务端重算后的合规评分 */
  send: (taskId: string, updates: ViolationStatusUpdate[], options: SendOptions) => Promise<number>;
  onSaved: (taskId: string, score: number) => void;
  /** willRetry 为 false 表示已放弃自动重试，需要用户介入 */
  onError: (willRetry: boolean) => void;
  debounceMs?: number;
  retryDelayMs?: number;
  maxRetries?: number;
}

/**
 * 复核结果的防抖持久化。
 *
 * - 500ms 内的多次修改合并为一次请求（同一违规只保留最后一次）
 * - 任务在入队时绑定，切换任务不会把 A 的修改提交给 B
 * - 请求严格串行，先发的评分响应不会覆盖后发的
 * - 失败后放回队列并指数退避重试，不静默丢失
 */
export class ReviewPersister {
  private pending = new Map<string, ViolationStatusUpdate>();
  private pendingTaskId: string | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private inFlight: Promise<void> = Promise.resolve();
  private failures = 0;

  private readonly deps: ReviewPersisterDeps;

  constructor(deps: ReviewPersisterDeps) {
    this.deps = deps;
  }

  private get debounceMs() { return this.deps.debounceMs ?? 500; }
  private get retryDelayMs() { return this.deps.retryDelayMs ?? 3000; }
  private get maxRetries() { return this.deps.maxRetries ?? 3; }

  schedule(taskId: string, update: ViolationStatusUpdate): void {
    if (this.pendingTaskId !== null && this.pendingTaskId !== taskId) {
      void this.flush(); // 先把上一个任务的修改发出去
    }
    this.pendingTaskId = taskId;
    this.pending.set(update.violation_id, update);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(), this.debounceMs);
  }

  /** 立即提交队列中的修改；返回的 Promise 在本次及之前的请求全部结束后完成。 */
  flush(options: SendOptions = { keepalive: false }): Promise<void> {
    clearTimeout(this.timer);
    const taskId = this.pendingTaskId;
    if (taskId === null || this.pending.size === 0) return this.inFlight;

    const batch = [...this.pending.values()];
    this.pending = new Map();
    this.pendingTaskId = null;
    this.inFlight = this.inFlight.then(() => this.transmit(taskId, batch, options));
    return this.inFlight;
  }

  /** 丢弃尚未提交的修改（切换工作区时调用）。 */
  discard(): void {
    clearTimeout(this.timer);
    this.pending = new Map();
    this.pendingTaskId = null;
    this.failures = 0;
  }

  private async transmit(taskId: string, batch: ViolationStatusUpdate[], options: SendOptions) {
    try {
      const score = await this.deps.send(taskId, batch, options);
      this.failures = 0;
      this.deps.onSaved(taskId, score);
    } catch {
      this.failures += 1;
      const willRetry = this.failures <= this.maxRetries;
      // 队列已被别的任务占用时无法回放，只能提示；否则放回队列（不覆盖期间产生的新修改）
      if (this.pendingTaskId === null || this.pendingTaskId === taskId) {
        this.pendingTaskId = taskId;
        for (const u of batch) {
          if (!this.pending.has(u.violation_id)) this.pending.set(u.violation_id, u);
        }
        if (willRetry) {
          const delay = this.retryDelayMs * 2 ** (this.failures - 1);
          clearTimeout(this.timer);
          this.timer = setTimeout(() => void this.flush(), delay);
        }
      }
      this.deps.onError(willRetry);
    }
  }
}
