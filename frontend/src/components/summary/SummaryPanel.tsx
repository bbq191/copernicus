import { useCallback, useEffect } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import { useEvaluationStore } from "../../stores/evaluationStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useTaskStore } from "../../stores/taskStore";
import { useToastStore } from "../../stores/toastStore";
import { evaluateText } from "../../api/evaluation";
import { rerunEvaluation, getTaskStatus } from "../../api/task";
import type { EvaluationResponse } from "../../types/evaluation";
import { ErrorAlert } from "../shared/ErrorAlert";
import { MetaInfo } from "./MetaInfo";
import { ScoreRadar } from "./ScoreRadar";
import { AnalysisSection } from "./AnalysisSection";

const POLL_INTERVAL_MS = 2000;

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中...",
  evaluating: "生成摘要中...",
};

export function SummaryPanel() {
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const evaluation = useEvaluationStore((s) => s.evaluation);
  const isLoading = useEvaluationStore((s) => s.isLoading);
  const error = useEvaluationStore((s) => s.error);
  const progress = useEvaluationStore((s) => s.progress);
  const progressText = useEvaluationStore((s) => s.progressText);
  const taskId = useTaskStore((s) => s.taskId);

  useEffect(() => {
    if (rawEntries.length === 0) return;

    const { evaluation: existing, isLoading: pending } =
      useEvaluationStore.getState();
    if (existing || pending) return;

    const fullText = rawEntries.map((e) => e.text_corrected).join("\n");
    if (!fullText.trim()) return;

    useEvaluationStore.getState().setLoading(true);

    evaluateText(fullText, taskId ?? undefined)
      .then((result) => {
        useEvaluationStore.getState().setEvaluation(result);
      })
      .catch((err) => {
        useEvaluationStore
          .getState()
          .setError(err instanceof Error ? err.message : "摘要生成失败");
      });
  }, [rawEntries, taskId]);

  const handleRerun = useCallback(async () => {
    if (!taskId) return;
    useEvaluationStore.getState().setLoading(true);
    useToastStore.getState().addToast("info", "重新评估已启动");

    try {
      const res = await rerunEvaluation(taskId);
      const childTaskId = res.task_id;

      const poll = async () => {
        const data = await getTaskStatus(childTaskId);
        if (data.status === "completed" && data.result) {
          const response = data.result as EvaluationResponse;
          useEvaluationStore.getState().setEvaluation(response.evaluation);
          return;
        }
        if (data.status === "failed") {
          useEvaluationStore.getState().setError(data.error || "评估失败");
          return;
        }
        const percent = data.progress?.percent ?? 0;
        const text = STATUS_TEXT[data.status] || "处理中...";
        useEvaluationStore.getState().setProgress(percent, text);
        setTimeout(poll, POLL_INTERVAL_MS);
      };
      poll();
    } catch (err) {
      useEvaluationStore
        .getState()
        .setError(err instanceof Error ? err.message : "重新评估失败");
    }
  }, [taskId]);

  if (rawEntries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-6 text-base-content/40">
        <Sparkles className="h-10 w-10 opacity-20" />
        <p className="font-medium text-sm">智能摘要</p>
        <p className="text-xs">转写完成后自动生成内容评估</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8">
        <span className="loading loading-spinner loading-lg text-primary" />
        <span className="text-base-content/60 text-sm">
          {progressText || "生成摘要中..."}
        </span>
        <div className="w-full max-w-xs">
          <progress
            className="progress progress-primary w-full"
            value={progress}
            max={100}
          />
          <span className="text-xs text-base-content/40 mt-1 block text-center">
            {Math.round(progress)}%
          </span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <ErrorAlert compact message={error} onRetry={handleRerun} />
      </div>
    );
  }

  if (!evaluation) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <MetaInfo meta={evaluation.meta} />
      <div className="divider my-0" />
      <ScoreRadar scores={evaluation.scores} />
      <div className="divider my-0" />
      <AnalysisSection analysis={evaluation.analysis} />
      {evaluation.summary && (
        <>
          <div className="divider my-0" />
          <div>
            <h4 className="font-semibold text-sm mb-1">总结</h4>
            <p className="text-sm">{evaluation.summary}</p>
          </div>
        </>
      )}
      <div className="divider my-0" />
      <button
        className="btn btn-sm btn-ghost btn-block gap-1"
        onClick={handleRerun}
      >
        <RefreshCw className="h-3.5 w-3.5" />
        重新评估
      </button>
    </div>
  );
}
