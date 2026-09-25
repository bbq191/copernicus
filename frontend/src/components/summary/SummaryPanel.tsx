import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import { useEvaluationStore } from "../../stores/evaluationStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useTaskStore } from "../../stores/taskStore";
import { useToastStore } from "../../stores/toastStore";
import { evaluateText } from "../../api/evaluation";
import { errorMessage } from "../../api/errors";
import { isAbortError } from "../../api/polling";
import { currentTaskSignal } from "../../stores/taskScope";
import { useTemplates } from "../../hooks/useTemplates";
import { StructuredMinutes } from "./StructuredMinutes";
import { IncompleteNotice } from "../shared/IncompleteNotice";
import { evaluationIncompleteness } from "../../utils/completeness";
import { ErrorAlert } from "../shared/ErrorAlert";
import { ProgressBlock } from "../shared/ProgressBlock";
import { TemplateSelect } from "../shared/TemplateSelect";
import type { TranscriptEntry } from "../../types/transcript";

/** 发起一次摘要评估。请求绑定当前任务范围：切换任务后，旧任务的结果与进度会被丢弃。 */
function startEvaluation(rawEntries: TranscriptEntry[], taskId: string | null, templateId: string, failedText: string) {
  const fullText = rawEntries.map((e) => e.text_corrected).join("\n");
  const signal = currentTaskSignal();
  const store = useEvaluationStore.getState();
  store.setLoading(true);

  evaluateText(fullText, taskId ?? undefined, templateId, {
    signal,
    onProgress: (percent, text) => useEvaluationStore.getState().setProgress(percent, text),
  })
    .then((result) => useEvaluationStore.getState().setEvaluation(result))
    .catch((err) => {
      if (signal.aborted || isAbortError(err)) return;
      useEvaluationStore.getState().setError(errorMessage(err, failedText));
    });
}

export function SummaryPanel() {
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const evaluation = useEvaluationStore((s) => s.evaluation);
  const isLoading = useEvaluationStore((s) => s.isLoading);
  const error = useEvaluationStore((s) => s.error);
  const progress = useEvaluationStore((s) => s.progress);
  const progressText = useEvaluationStore((s) => s.progressText);
  const taskId = useTaskStore((s) => s.taskId);

  const templates = useTemplates();
  const [templateId, setTemplateId] = useState("universal");

  // 转写就绪后自动生成一次摘要；已有摘要（含从服务端恢复的）或正在生成时不重复提交
  useEffect(() => {
    if (rawEntries.length === 0) return;
    const { evaluation: existing, isLoading: pending } = useEvaluationStore.getState();
    if (existing || pending) return;
    if (!rawEntries.some((e) => e.text_corrected.trim())) return;
    startEvaluation(rawEntries, taskId, templateId, "摘要生成失败");
  }, [rawEntries, taskId, templateId]);

  const handleRerun = useCallback(() => {
    if (!taskId || rawEntries.length === 0) return;
    useToastStore.getState().addToast("info", "重新评估已启动");
    startEvaluation(rawEntries, taskId, templateId, "重新评估失败");
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
    return <ProgressBlock text={progressText || "生成摘要中..."} percent={progress} className="p-8" />;
  }

  if (error) {
    return (
      <div className="p-4">
        <ErrorAlert compact message={error} onRetry={handleRerun} />
      </div>
    );
  }

  const templateSelector = (
    <TemplateSelect
      templates={templates}
      value={templateId}
      onChange={setTemplateId}
      disabled={isLoading}
      className="select-xs w-full"
    />
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
      <IncompleteNotice notes={evaluationIncompleteness(evaluation)} />
      {evaluation.title && (
        <h3 className="font-bold text-base">{evaluation.title}</h3>
      )}
      {evaluation.formatted_content && (
        <div className="text-sm text-base-content/80 whitespace-pre-wrap leading-relaxed">
          {evaluation.formatted_content}
        </div>
      )}
      <StructuredMinutes evaluation={evaluation} />
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
