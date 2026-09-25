import { useComplianceStore, flushReviews } from "./complianceStore";
import { useEvaluationStore } from "./evaluationStore";
import { usePlayerStore } from "./playerStore";
import { useSynthesisStore } from "./synthesisStore";
import { useTaskStore } from "./taskStore";
import { cancelTaskWork } from "./taskScope";
import { useTranscriptStore } from "./transcriptStore";

/**
 * 清空与具体任务绑定的工作区状态，避免切换任务时残留上一个任务的内容。
 *
 * 先停掉旧任务的在途请求与轮询；尚未提交的复核结果默认先补交（绑定的是它们所属的任务）。
 * 服务端已经清除了合规结果时（重新转写）传 serverCleared，丢弃即可，补交只会 404。
 */
export function resetWorkspaceStores({ serverCleared = false } = {}) {
  cancelTaskWork();
  if (!serverCleared) void flushReviews();
  useTaskStore.getState().reset();
  useTranscriptStore.getState().setRawEntries([]);
  useEvaluationStore.getState().reset();
  useComplianceStore.getState().reset();
  useSynthesisStore.getState().reset();
  usePlayerStore.getState().resetMedia();
}
