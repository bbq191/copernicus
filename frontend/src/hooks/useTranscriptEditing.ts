import { useCallback } from "react";
import { editTranscript, renameSpeakers } from "../api/task";
import { useTaskStore } from "../stores/taskStore";
import { useToastStore } from "../stores/toastStore";
import { useTranscriptStore } from "../stores/transcriptStore";
import type { TranscriptEntry } from "../types/transcript";

/** 转写人工校对：乐观更新本地状态，同步到后端，失败时回滚并提示。 */
export function useTranscriptEditing() {
  const taskId = useTaskStore((s) => s.taskId);

  const editSentence = useCallback(
    async (entry: TranscriptEntry, text: string) => {
      const next = text.trim();
      const previous = entry.text_corrected;
      const { rawEntries, setSentenceText } = useTranscriptStore.getState();
      const index = rawEntries.indexOf(entry);
      if (!taskId || index < 0 || !next || next === previous) return;

      setSentenceText(index, next);
      try {
        await editTranscript(taskId, [{ index, text_corrected: next }]);
      } catch (err) {
        setSentenceText(index, previous);
        useToastStore
          .getState()
          .addToast("error", err instanceof Error ? `保存失败：${err.message}` : "保存失败");
      }
    },
    [taskId],
  );

  /** 重命名或合并说话人（多个原名指向同一新名即合并）；返回是否成功。 */
  const renameSpeakerLabels = useCallback(
    async (renames: Record<string, string>): Promise<boolean> => {
      const changes = Object.fromEntries(
        Object.entries(renames).filter(([from, to]) => to.trim() && to.trim() !== from),
      );
      if (!taskId || Object.keys(changes).length === 0) return true;

      try {
        await renameSpeakers(taskId, changes);
        useTranscriptStore.getState().applySpeakerRenames(changes);
        useToastStore.getState().addToast("success", "说话人已更新");
        return true;
      } catch (err) {
        useToastStore
          .getState()
          .addToast("error", err instanceof Error ? `保存失败：${err.message}` : "保存失败");
        return false;
      }
    },
    [taskId],
  );

  return { editSentence, renameSpeakerLabels };
}
