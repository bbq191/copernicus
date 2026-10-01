import { useComplianceStore, flushReviews } from "./complianceStore";
import { useEvaluationStore } from "./evaluationStore";
import { usePlayerStore } from "./playerStore";
import { useSynthesisStore } from "./synthesisStore";
import { useTaskStore } from "./taskStore";
import { cancelTaskWork } from "./taskScope";
import { discardTranscriptEdits, flushTranscriptEdits } from "./transcriptPersister";
import { useTranscriptStore } from "./transcriptStore";

/**
 * 清空与具体任务绑定的工作区状态，避免切换任务时残留上一个任务的内容。
 *
 * 先停掉旧任务的在途请求与轮询；尚未提交的复核结果与转写校对默认先补交（绑定的是它们所属的任务）。
 * 服务端已经清除了旧内容时（重新转写）传 serverCleared，丢弃即可，补交只会落到已不存在的内容上。
 */
export function resetWorkspaceStores({ serverCleared = false } = {}) {
  cancelTaskWork();
  if (!serverCleared) {
    void flushReviews();
    void flushTranscriptEdits();
  } else {
    discardTranscriptEdits();
  }
  useTaskStore.getState().reset();
  useTranscriptStore.getState().setRawEntries([]);
  useEvaluationStore.getState().reset();
  useComplianceStore.getState().reset();
  useSynthesisStore.getState().reset();
  usePlayerStore.getState().resetMedia();
}
