import { editTranscript } from "../api/task";
import type { TranscriptTextEdit } from "../types/task";
import { useToastStore } from "./toastStore";
import { DebouncedPersister } from "./debouncedPersister";

// ---------------------------------------------------------------------------
// 转写校对的持久化（防抖、按任务绑定、失败重试；细节见 DebouncedPersister）
// ---------------------------------------------------------------------------
const persister = new DebouncedPersister<number, TranscriptTextEdit, void>({
  key: (edit) => edit.index,
  send: (taskId, edits, options) => editTranscript(taskId, edits, options),
  onSaved: () => {},
  onError: (willRetry) => {
    useToastStore
      .getState()
      .addToast("error", willRetry ? "转写修改保存失败，稍后将自动重试" : "转写修改多次保存失败，请检查网络后重新编辑以重试");
  },
});

/** 排队一条句子修正文的修改（本地状态由调用方自行乐观更新）。 */
export function scheduleTranscriptEdit(taskId: string, edit: TranscriptTextEdit): void {
  persister.schedule(taskId, edit);
}

/** 立即提交尚未保存的转写修改（切换任务、关闭页面前调用）。 */
export function flushTranscriptEdits(options?: { keepalive: boolean }): Promise<void> {
  return persister.flush(options);
}

/** 丢弃尚未提交的转写修改（重置工作区时调用）。 */
export function discardTranscriptEdits(): void {
  persister.discard();
}

if (typeof document !== "undefined") {
  // 标签页转入后台或关闭时，防抖窗口内的修改不能丢
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flushTranscriptEdits({ keepalive: true });
  });
  window.addEventListener("pagehide", () => void flushTranscriptEdits({ keepalive: true }));
}
