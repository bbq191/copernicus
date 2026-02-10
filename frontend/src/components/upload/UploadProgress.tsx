import { Mic, FileCheck, Sparkles, Check } from "lucide-react";
import { useTaskStore } from "../../stores/taskStore";
import type { TaskStatus } from "../../types/task";

interface PipelineStage {
  key: string;
  label: string;
  icon: typeof Mic;
}

const STAGES: PipelineStage[] = [
  { key: "processing_asr", label: "语音识别", icon: Mic },
  { key: "correcting", label: "文本纠正", icon: FileCheck },
  { key: "evaluating", label: "内容评估", icon: Sparkles },
];

const STAGE_ORDER: Record<string, number> = {
  pending: -1,
  processing_asr: 0,
  correcting: 1,
  evaluating: 2,
  auditing: 3,
  completed: 4,
  failed: -2,
};

function getStageState(
  stageIndex: number,
  status: TaskStatus,
): "done" | "active" | "pending" | "error" {
  const currentIndex = STAGE_ORDER[status] ?? -1;
  if (status === "failed" && currentIndex === -2) {
    // Find which stage failed based on progress or default to first
    return "error";
  }
  if (status === "completed") return "done";
  if (stageIndex < currentIndex) return "done";
  if (stageIndex === currentIndex) return status === "failed" ? "error" : "active";
  return "pending";
}

const STATE_CLASS: Record<string, string> = {
  done: "step-primary",
  active: "step-primary",
  error: "step-error",
  pending: "",
};

export function UploadProgress() {
  const status = useTaskStore((s) => s.status);
  const progress = useTaskStore((s) => s.progress);
  const error = useTaskStore((s) => s.error);

  if (!status) return null;

  // Dynamically add auditing stage if task reaches it
  const stages =
    status === "auditing"
      ? [...STAGES, { key: "auditing", label: "合规审核", icon: FileCheck }]
      : STAGES;

  const currentIndex = STAGE_ORDER[status] ?? -1;

  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-lg">
      {/* Pipeline Steps */}
      <ul className="steps steps-horizontal w-full">
        {stages.map((stage, i) => {
          const state = getStageState(i, status);
          return (
            <li key={stage.key} className={`step ${STATE_CLASS[state]}`}>
              <span className="flex items-center gap-1 text-xs">
                {state === "done" ? (
                  <Check className="h-3 w-3" />
                ) : (
                  <stage.icon className="h-3 w-3" />
                )}
                {stage.label}
              </span>
            </li>
          );
        })}
      </ul>

      {/* Current stage progress */}
      {status !== "completed" && status !== "failed" && (
        <div className="flex flex-col gap-2 w-full max-w-xs">
          <progress
            className="progress progress-primary w-full"
            value={progress.percent}
            max={100}
          />
          <div className="flex justify-between text-xs text-base-content/60">
            <span>
              {currentIndex >= 0 && currentIndex < stages.length
                ? `${stages[currentIndex].label}...`
                : "处理中..."}
            </span>
            <span>{Math.round(progress.percent)}%</span>
          </div>
          {progress.total_chunks > 0 && (
            <div className="text-xs text-base-content/40 text-center">
              {progress.current_chunk} / {progress.total_chunks} 分块
            </div>
          )}
        </div>
      )}

      {/* Completed */}
      {status === "completed" && (
        <div className="text-sm text-success font-medium">处理完成</div>
      )}

      {/* Error */}
      {error && (
        <div className="text-sm text-error text-center">{error}</div>
      )}
    </div>
  );
}
