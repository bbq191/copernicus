export interface SendOptions {
  /** 页面即将关闭时使用，请求在页面卸载后仍会被浏览器发完 */
  keepalive: boolean;
}

export interface DebouncedPersisterDeps<TKey, TUpdate, TResult> {
  /** 提交一批修改，返回服务端的处理结果 */
  send: (taskId: string, updates: TUpdate[], options: SendOptions) => Promise<TResult>;
  /** 同一个 key 在防抖窗口内的多次修改只保留最后一次 */
  key: (update: TUpdate) => TKey;
  onSaved: (taskId: string, result: TResult) => void;
  /** willRetry 为 false 表示已放弃自动重试，需要用户介入 */
  onError: (willRetry: boolean) => void;
  debounceMs?: number;
  retryDelayMs?: number;
  maxRetries?: number;
}

/**
 * 防抖持久化（复核结果、转写校对等按条目修改的场景共用）。
 *
 * - 防抖窗口内的多次修改合并为一次请求（同一 key 只保留最后一次）
 * - 任务在入队时绑定，切换任务不会把 A 的修改提交给 B
 * - 请求严格串行，先发的响应不会覆盖后发的
 * - 失败后放回队列并指数退避重试，不静默丢失
 */
export class DebouncedPersister<TKey, TUpdate, TResult> {
  private pending = new Map<TKey, TUpdate>();
  private pendingTaskId: string | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private inFlight: Promise<void> = Promise.resolve();
  private failures = 0;

  private readonly deps: DebouncedPersisterDeps<TKey, TUpdate, TResult>;

  constructor(deps: DebouncedPersisterDeps<TKey, TUpdate, TResult>) {
    this.deps = deps;
  }

  private get debounceMs() { return this.deps.debounceMs ?? 500; }
  private get retryDelayMs() { return this.deps.retryDelayMs ?? 3000; }
  private get maxRetries() { return this.deps.maxRetries ?? 3; }

  schedule(taskId: string, update: TUpdate): void {
    if (this.pendingTaskId !== null && this.pendingTaskId !== taskId) {
      void this.flush(); // 先把上一个任务的修改发出去
    }
    this.pendingTaskId = taskId;
    this.pending.set(this.deps.key(update), update);
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

  private async transmit(taskId: string, batch: TUpdate[], options: SendOptions) {
    try {
      const result = await this.deps.send(taskId, batch, options);
      this.failures = 0;
      this.deps.onSaved(taskId, result);
    } catch {
      this.failures += 1;
      const willRetry = this.failures <= this.maxRetries;
      // 队列已被别的任务占用时无法回放，只能提示；否则放回队列（不覆盖期间产生的新修改）
      if (this.pendingTaskId === null || this.pendingTaskId === taskId) {
        this.pendingTaskId = taskId;
        for (const u of batch) {
          const k = this.deps.key(u);
          if (!this.pending.has(k)) this.pending.set(k, u);
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
