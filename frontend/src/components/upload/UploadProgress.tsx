import { Mic, FileCheck, Sparkles, Check, Film, ScanText } from "lucide-react";
import { useTaskStore } from "../../stores/taskStore";
import type { TaskStatus } from "../../types/task";

interface PipelineStage {
  key: string;
  label: string;
  icon: typeof Mic;
}

const STAGES_AUDIO: PipelineStage[] = [
  { key: "processing_asr", label: "语音识别", icon: Mic },
  { key: "correcting", label: "文本纠正", icon: FileCheck },
  { key: "evaluating", label: "内容评估", icon: Sparkles },
];

const STAGES_VIDEO: PipelineStage[] = [
  { key: "extracting_frames", label: "提取帧", icon: Film },
  { key: "scanning_visual", label: "视觉扫描", icon: ScanText },
  { key: "processing_asr", label: "语音识别", icon: Mic },
  { key: "correcting", label: "文本纠正", icon: FileCheck },
  { key: "evaluating", label: "内容评估", icon: Sparkles },
];

function getStageState(
  stageIndex: number,
  currentStageIndex: number,
  status: TaskStatus,
): "done" | "active" | "pending" | "error" {
  if (status === "failed") return stageIndex === currentStageIndex ? "error" : stageIndex < currentStageIndex ? "done" : "pending";
  if (status === "completed") return "done";
  if (stageIndex < currentStageIndex) return "done";
  if (stageIndex === currentStageIndex) return "active";
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
  const isVideoTask = useTaskStore((s) => s.isVideoTask);

  if (!status) return null;

  const baseStages = isVideoTask ? STAGES_VIDEO : STAGES_AUDIO;
  const stages =
    status === "auditing"
      ? [...baseStages, { key: "auditing", label: "合规审核", icon: FileCheck }]
      : baseStages;

  const currentStageIndex = stages.findIndex((s) => s.key === status);

  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-lg">
      {/* Pipeline Steps */}
      <ul className="steps steps-horizontal w-full">
        {stages.map((stage, i) => {
          const state = getStageState(i, currentStageIndex, status);
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
              {currentStageIndex >= 0
                ? `${stages[currentStageIndex].label}...`
                : "处理中..."}
            </span>
            <span>{Math.round(progress.percent)}%</span>
          </div>
          {progress.total_chunks > 0 && (
            <div className="text-xs text-base-content/40 text-center">
              {progress.current_chunk} / {progress.total_chunks}{" "}
              {status === "scanning_visual" ? "帧" : "分块"}
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
