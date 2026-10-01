import type { ViolationStatusUpdate } from "../api/compliance";
import { DebouncedPersister } from "./debouncedPersister";
import type { SendOptions } from "./debouncedPersister";

export type { SendOptions };

export interface ReviewPersisterDeps {
  send: (taskId: string, updates: ViolationStatusUpdate[], options: SendOptions) => Promise<number>;
  onSaved: (taskId: string, score: number) => void;
  /** willRetry 为 false 表示已放弃自动重试，需要用户介入 */
  onError: (willRetry: boolean) => void;
  debounceMs?: number;
  retryDelayMs?: number;
  maxRetries?: number;
}

/** 复核结果的防抖持久化，细节见 {@link DebouncedPersister}。 */
export class ReviewPersister extends DebouncedPersister<string, ViolationStatusUpdate, number> {
  constructor(deps: ReviewPersisterDeps) {
    super({ ...deps, key: (u) => u.violation_id });
  }
}
