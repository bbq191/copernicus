import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import { useEvaluationStore } from "../../stores/evaluationStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useTaskStore } from "../../stores/taskStore";
import { useToastStore } from "../../stores/toastStore";
import { evaluateText } from "../../api/evaluation";
import { listTemplates } from "../../api/templates";
import type { TemplateInfo } from "../../api/templates";
import { ErrorAlert } from "../shared/ErrorAlert";

export function SummaryPanel() {
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const evaluation = useEvaluationStore((s) => s.evaluation);
  const isLoading = useEvaluationStore((s) => s.isLoading);
  const error = useEvaluationStore((s) => s.error);
  const progress = useEvaluationStore((s) => s.progress);
  const progressText = useEvaluationStore((s) => s.progressText);
  const taskId = useTaskStore((s) => s.taskId);

  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [templateId, setTemplateId] = useState("universal");

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (rawEntries.length === 0) return;

    const { evaluation: existing, isLoading: pending } =
      useEvaluationStore.getState();
    if (existing || pending) return;

    const fullText = rawEntries.map((e) => e.text_corrected).join("\n");
    if (!fullText.trim()) return;

    useEvaluationStore.getState().setLoading(true);

    evaluateText(fullText, taskId ?? undefined, templateId)
      .then((result) => {
        useEvaluationStore.getState().setEvaluation(result);
      })
      .catch((err) => {
        useEvaluationStore
          .getState()
          .setError(err instanceof Error ? err.message : "摘要生成失败");
      });
  }, [rawEntries, taskId, templateId]);

  const handleRerun = useCallback(async () => {
    if (!taskId || rawEntries.length === 0) return;
    useEvaluationStore.getState().setLoading(true);
    useToastStore.getState().addToast("info", "重新评估已启动");

    const fullText = rawEntries.map((e) => e.text_corrected).join("\n");
    try {
      const result = await evaluateText(fullText, taskId, templateId);
      useEvaluationStore.getState().setEvaluation(result);
    } catch (err) {
      useEvaluationStore
        .getState()
        .setError(err instanceof Error ? err.message : "重新评估失败");
    }
  }, [taskId, rawEntries, templateId]);

  if (rawEntries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-6 text-base-content/40">
        <Sparkles className="h-10 w-10 opacity-20" />
        <p className="font-medium text-sm">智能摘要</p>
        <p className="text-xs">转写完成后自动生成内容摘要</p>
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

  const templateSelector = templates.length > 1 && (
    <select
      className="select select-bordered select-xs w-full"
      value={templateId}
      onChange={(e) => setTemplateId(e.target.value)}
      disabled={isLoading}
    >
      {templates.map((t) => (
        <option key={t.id} value={t.id} title={t.description}>
          {t.name}
        </option>
      ))}
    </select>
  );

  if (!evaluation) {
    return (
      <div className="flex flex-col gap-3 p-4">
        {templateSelector}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {evaluation.title && (
        <h3 className="font-bold text-base">{evaluation.title}</h3>
      )}
      {evaluation.formatted_content && (
        <div className="text-sm text-base-content/80 whitespace-pre-wrap leading-relaxed">
          {evaluation.formatted_content}
        </div>
      )}
      <div className="divider my-0" />
      {templateSelector}
      <button
        className="btn btn-sm btn-ghost btn-block gap-1"
        onClick={handleRerun}
        disabled={isLoading}
      >
        <RefreshCw className="h-3.5 w-3.5" />
        重新评估
      </button>
    </div>
  );
}
