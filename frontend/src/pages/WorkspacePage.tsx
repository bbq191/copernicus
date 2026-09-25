import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useTaskStore } from "../stores/taskStore";
import { usePlayerStore } from "../stores/playerStore";
import { hydrateWorkspace } from "../stores/hydrateWorkspace";
import { resetWorkspaceStores } from "../stores/resetWorkspace";
import { useTaskPolling } from "../hooks/useTaskPolling";
import { getTaskResults, getTaskMediaUrl } from "../api/task";
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
  const mediaSrc = usePlayerStore((s) => s.mediaSrc);
  const setMediaSrc = usePlayerStore((s) => s.setMediaSrc);

  useEffect(() => {
    if (taskId && taskId !== currentTaskId) {
      resetWorkspaceStores();
      setTask(taskId, "pending");
    }
  }, [taskId, currentTaskId, setTask]);

  // 进入页面先尝试恢复已持久化的结果；恢复完成前不启动轮询，
  // 保证摘要/合规 store 在 SummaryPanel 挂载前就已就绪。
  useEffect(() => {
    if (!taskId) return;

    let cancelled = false;
    getTaskResults(taskId)
      .then((res) => {
        if (cancelled) return;
        if (hydrateWorkspace(taskId, res)) {
          updateStatus("completed", { current_chunk: 0, total_chunks: 0, percent: 100 });
        } else {
          setPollEnabled(true); // 转写还没落盘：任务仍在处理，开始轮询
        }
      })
      .catch(() => {
        if (!cancelled) setPollEnabled(true); // 没有持久化结果：以轮询兜底
      });

    return () => { cancelled = true; };
  }, [taskId, updateStatus, setPollEnabled]);

  useEffect(() => {
    if (!taskId || mediaSrc) return;
    setMediaSrc(getTaskMediaUrl(taskId));
  }, [taskId, mediaSrc, setMediaSrc]);

  useTaskPolling(pollEnabled);

  // 路由已切到新任务、但 store 还是上一个任务的数据（重置发生在渲染之后的 effect 里）：
  // 先显示骨架屏，避免用旧数据渲染一帧并触发旧媒体的加载
  if (taskId && taskId !== currentTaskId) return <WorkspaceSkeleton />;

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-8">
        <ErrorAlert message={error} />
        <Link to="/" className="btn btn-sm btn-ghost">返回首页</Link>
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
