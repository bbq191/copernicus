import { useComplianceStore } from "./complianceStore";
import { useEvaluationStore } from "./evaluationStore";
import { usePlayerStore } from "./playerStore";
import { useSynthesisStore } from "./synthesisStore";
import { useTranscriptStore } from "./transcriptStore";

/** 清空与具体任务绑定的工作区状态，避免切换任务时残留上一个任务的内容。 */
export function resetWorkspaceStores() {
  useTranscriptStore.getState().setRawEntries([]);
  useEvaluationStore.getState().reset();
  useComplianceStore.getState().reset();
  useSynthesisStore.getState().reset();
  usePlayerStore.getState().resetMedia();
}
