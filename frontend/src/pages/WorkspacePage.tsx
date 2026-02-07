import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useTaskStore } from "../stores/taskStore";
import { usePlayerStore } from "../stores/playerStore";
import { useTaskPolling } from "../hooks/useTaskPolling";
import { AppLayout } from "../components/layout/AppLayout";
import { LoadingSpinner } from "../components/shared/LoadingSpinner";
import { ErrorAlert } from "../components/shared/ErrorAlert";
import { UploadProgress } from "../components/upload/UploadProgress";

export function WorkspacePage() {
  const { taskId } = useParams<{ taskId: string }>();
  const currentTaskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);
  const error = useTaskStore((s) => s.error);
  const setTask = useTaskStore((s) => s.setTask);
  const audioSrc = usePlayerStore((s) => s.audioSrc);
  const setAudioSrc = usePlayerStore((s) => s.setAudioSrc);

  useEffect(() => {
    if (taskId && taskId !== currentTaskId) {
      setTask(taskId, "pending");
    }
  }, [taskId, currentTaskId, setTask]);

  useEffect(() => {
    if (!taskId || audioSrc) return;
    setAudioSrc(`/api/v1/tasks/${taskId}/audio`);
  }, [taskId, audioSrc, setAudioSrc]);

  useTaskPolling();

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <ErrorAlert message={error} />
      </div>
    );
  }

  if (status && status !== "completed") {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-8">
        <LoadingSpinner text="处理中..." />
        <UploadProgress />
      </div>
    );
  }

  return <AppLayout />;
}
