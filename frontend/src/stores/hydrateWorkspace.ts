import { getTaskMediaUrl } from "../api/task";
import type { TaskResultsResponse } from "../types/task";
import { useComplianceStore } from "./complianceStore";
import { useEvaluationStore } from "./evaluationStore";
import { usePlayerStore } from "./playerStore";
import { useSynthesisStore } from "./synthesisStore";
import { useTranscriptStore } from "./transcriptStore";

/**
 * 把服务端持久化的任务结果灌进各 store。
 *
 * 顺序有意义：纪要/合规必须先于转写写入，这样 SummaryPanel 挂载时能看到已有摘要，
 * 不会用默认模板重复提交一次评估。调用方在此之后再把任务状态置为 completed。
 * 返回是否包含转写（无转写说明任务还没跑完）。
 */
export function hydrateWorkspace(taskId: string, res: TaskResultsResponse): boolean {
  if (!res.transcript) return false;

  if (res.evaluation) useEvaluationStore.getState().setEvaluation(res.evaluation);
  if (res.compliance) useComplianceStore.getState().setReport(res.compliance.report, res.compliance.rules);
  if (res.has_video) usePlayerStore.getState().setMediaSrc(getTaskMediaUrl(taskId), "video");
  if (res.has_synthesis) useSynthesisStore.getState().setHasSynthesis(true);
  useTranscriptStore.getState().setRawEntries(res.transcript.transcript);
  return true;
}
