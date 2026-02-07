import { useTaskStore } from "../../stores/taskStore";
import type { TaskStatus } from "../../types/task";

const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: "等待处理...",
  processing_asr: "语音识别中...",
  correcting: "文本纠正中...",
  evaluating: "内容评估中...",
  auditing: "合规审核中...",
  completed: "处理完成",
  failed: "处理失败",
};

export function UploadProgress() {
  const status = useTaskStore((s) => s.status);
  const progress = useTaskStore((s) => s.progress);
  const error = useTaskStore((s) => s.error);

  if (!status) return null;

  return (
    <div className="flex flex-col gap-3 w-full max-w-md">
      <div className="flex justify-between text-sm">
        <span>{STATUS_LABELS[status]}</span>
        <span>{Math.round(progress.percent)}%</span>
      </div>
      <progress
        className={`progress w-full ${status === "failed" ? "progress-error" : "progress-primary"}`}
        value={progress.percent}
        max={100}
      />
      {progress.total_chunks > 0 && (
        <div className="text-xs text-base-content/60 text-center">
          {progress.current_chunk} / {progress.total_chunks} 分块
        </div>
      )}
      {error && (
        <div className="text-sm text-error text-center">{error}</div>
      )}
    </div>
  );
}
