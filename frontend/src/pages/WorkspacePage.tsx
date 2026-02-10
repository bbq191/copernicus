import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useTaskStore } from "../stores/taskStore";
import { usePlayerStore } from "../stores/playerStore";
import { useTranscriptStore } from "../stores/transcriptStore";
import { useEvaluationStore } from "../stores/evaluationStore";
import { useComplianceStore } from "../stores/complianceStore";
import { useTaskPolling } from "../hooks/useTaskPolling";
import { getTaskResults } from "../api/task";
import { AppLayout } from "../components/layout/AppLayout";
import { ErrorAlert } from "../components/shared/ErrorAlert";
import { WorkspaceSkeleton } from "../components/shared/WorkspaceSkeleton";
import { UploadProgress } from "../components/upload/UploadProgress";

export function WorkspacePage() {
  const { taskId } = useParams<{ taskId: string }>();
  const currentTaskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);
  const error = useTaskStore((s) => s.error);
  const setTask = useTaskStore((s) => s.setTask);
  const updateStatus = useTaskStore((s) => s.updateStatus);
  const setPollEnabled = useTaskStore((s) => s.setPollEnabled);
  const pollEnabled = useTaskStore((s) => s.pollEnabled);
  const audioSrc = usePlayerStore((s) => s.audioSrc);
  const setAudioSrc = usePlayerStore((s) => s.setAudioSrc);

  useEffect(() => {
    if (taskId && taskId !== currentTaskId) {
      setTask(taskId, "pending");
    }
  }, [taskId, currentTaskId, setTask]);

  // Try to restore persisted results on mount.
  // Polling is held back until this completes so that evaluation/compliance
  // stores are populated before SummaryPanel mounts.
  useEffect(() => {
    if (!taskId) return;

    let cancelled = false;
    getTaskResults(taskId)
      .then((res) => {
        if (cancelled) return;
        if (res.transcript) {
          // Restore evaluation and compliance BEFORE setting status to
          // "completed", so that SummaryPanel sees them on mount.
          if (res.evaluation) {
            useEvaluationStore.getState().setEvaluation(res.evaluation);
          }
          if (res.compliance) {
            useComplianceStore.getState().setReport(res.compliance.report, res.compliance.rules);
          }
          useTranscriptStore.getState().setRawEntries(res.transcript.transcript);
          updateStatus("completed", { current_chunk: 0, total_chunks: 0, percent: 100 });
          // No need to enable polling -- already restored
          return;
        }
        // transcript not persisted -- enable polling to track in-progress task
        setPollEnabled(true);
      })
      .catch(() => {
        // No persisted results -- enable polling as fallback
        if (!cancelled) setPollEnabled(true);
      });

    return () => { cancelled = true; };
  }, [taskId, updateStatus, setPollEnabled]);

  useEffect(() => {
    if (!taskId || audioSrc) return;
    setAudioSrc(`/api/v1/tasks/${taskId}/audio`);
  }, [taskId, audioSrc, setAudioSrc]);

  useTaskPolling(pollEnabled);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <ErrorAlert message={error} />
      </div>
    );
  }

  if (status && status !== "completed") {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-6 p-8">
        <span className="loading loading-spinner loading-lg text-primary" />
        <UploadProgress />
      </div>
    );
  }

  if (!status) return <WorkspaceSkeleton />;

  return <AppLayout />;
}
