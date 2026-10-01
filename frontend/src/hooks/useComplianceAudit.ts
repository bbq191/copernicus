import { useCallback, useRef } from "react";
import { useTranscriptStore } from "../stores/transcriptStore";
import { useComplianceStore } from "../stores/complianceStore";
import { useTaskStore } from "../stores/taskStore";
import { auditCompliance, type RulesSource } from "../api/compliance";
import { errorMessage } from "../api/errors";
import { isAbortError } from "../api/polling";
import { currentTaskSignal } from "../stores/taskScope";

/** 提交合规审核（上传规则文件或使用规则库），及其进度/结果/错误状态。 */
export function useComplianceAudit() {
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const report = useComplianceStore((s) => s.report);
  const isLoading = useComplianceStore((s) => s.isLoading);
  const error = useComplianceStore((s) => s.error);
  const progress = useComplianceStore((s) => s.progress);
  const progressText = useComplianceStore((s) => s.progressText);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = useCallback(
    (rulesSource: RulesSource) => {
      if (rawEntries.length === 0) return;

      if (useComplianceStore.getState().isLoading) return;
      useComplianceStore.getState().setLoading(true);

      // 请求绑定当前任务范围：切换任务后，旧任务的结果与进度会被丢弃
      const signal = currentTaskSignal();
      const taskId = useTaskStore.getState().taskId ?? undefined;

      auditCompliance(rawEntries, rulesSource, taskId, {
        signal,
        onProgress: (percent, text) => useComplianceStore.getState().setProgress(percent, text),
      })
        .then((res) => useComplianceStore.getState().setReport(res.report, res.rules))
        .catch((err) => {
          if (signal.aborted || isAbortError(err)) return;
          useComplianceStore.getState().setError(errorMessage(err, "合规审核失败"));
        });
    },
    [rawEntries],
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) submit(file);
      e.target.value = "";
    },
    [submit],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) submit(file);
    },
    [submit],
  );

  return { rawEntries, report, isLoading, error, progress, progressText, fileRef, submit, onFileChange, onDrop };
}
