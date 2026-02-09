import {
  Clock,
  AlertTriangle,
  AlertCircle,
  Info,
  Check,
  X,
  RotateCcw,
} from "lucide-react";
import type { Violation } from "../../types/compliance";
import { usePlayerStore } from "../../stores/playerStore";
import { useComplianceStore } from "../../stores/complianceStore";
import { formatTime } from "../../utils/formatTime";

interface Props {
  violation: Violation;
  isSelected: boolean;
  onClick: () => void;
}

const SEVERITY_CONFIG = {
  high: {
    badge: "badge-error",
    border: "border-error/30",
    bg: "bg-error/5",
    icon: AlertTriangle,
    label: "高",
  },
  medium: {
    badge: "badge-warning",
    border: "border-warning/30",
    bg: "bg-warning/5",
    icon: AlertCircle,
    label: "中",
  },
  low: {
    badge: "badge-info",
    border: "border-info/30",
    bg: "bg-info/5",
    icon: Info,
    label: "低",
  },
} as const;

const STATUS_CONFIG = {
  confirmed: {
    badge: "badge-success",
    label: "已确认",
    border: "border-success/30",
  },
  rejected: {
    badge: "badge-ghost",
    label: "已忽略",
    border: "border-base-300",
  },
} as const;

const LOOP_PADDING_MS = 10000;

export function ViolationCard({ violation, isSelected, onClick }: Props) {
  const seekAndPlay = usePlayerStore((s) => s.seekAndPlay);
  const setLoopRegion = usePlayerStore((s) => s.setLoopRegion);
  const setViolationStatus = useComplianceStore((s) => s.setViolationStatus);
  const setActiveTab = useComplianceStore((s) => s.setActiveTab);

  const config = SEVERITY_CONFIG[violation.severity] || SEVERITY_CONFIG.low;
  const SeverityIcon = config.icon;
  const isPending = violation.status === "pending";
  const statusConfig =
    !isPending && violation.status in STATUS_CONFIG
      ? STATUS_CONFIG[violation.status as "confirmed" | "rejected"]
      : null;

  const jumpToViolation = () => {
    const startMs = Math.max(0, violation.timestamp_ms - 5000);
    const endMs = (violation.end_ms || violation.timestamp_ms) + LOOP_PADDING_MS;
    setLoopRegion({ startMs, endMs });
    seekAndPlay(startMs);
    setActiveTab("transcript");
  };

  const handleTimestampClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    jumpToViolation();
  };

  const handleConfirm = (e: React.MouseEvent) => {
    e.stopPropagation();
    setViolationStatus(violation, "confirmed");
  };

  const handleReject = (e: React.MouseEvent) => {
    e.stopPropagation();
    setViolationStatus(violation, "rejected");
  };

  const handleReset = (e: React.MouseEvent) => {
    e.stopPropagation();
    setViolationStatus(violation, "pending");
  };

  const borderClass = statusConfig ? statusConfig.border : config.border;

  return (
    <div
      className={`card card-compact border cursor-pointer transition-all ${borderClass} ${
        isSelected ? `${config.bg} ring-2 ring-primary` : "hover:bg-base-200"
      } ${!isPending ? "opacity-75" : ""}`}
      onClick={onClick}
    >
      <div className="card-body gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            className="badge badge-ghost badge-sm gap-1 hover:badge-primary"
            onClick={handleTimestampClick}
          >
            <Clock className="h-3 w-3" />
            {formatTime(violation.timestamp_ms)}
          </button>

          <span className={`badge badge-sm gap-1 ${config.badge}`}>
            <SeverityIcon className="h-3 w-3" />
            {config.label}
          </span>

          {violation.speaker && (
            <span className="badge badge-ghost badge-sm">
              {violation.speaker}
            </span>
          )}

          {statusConfig && (
            <span className={`badge badge-sm ${statusConfig.badge}`}>
              {statusConfig.label}
            </span>
          )}

          <span className="text-xs text-base-content/40 ml-auto">
            {Math.round(violation.confidence * 100)}%
          </span>
        </div>

        <p className="text-sm">{violation.reason}</p>

        {violation.original_text && (
          <blockquote className="text-xs text-base-content/60 border-l-2 border-base-300 pl-2 italic">
            {violation.original_text}
          </blockquote>
        )}

        <div
          className="text-xs text-base-content/40 tooltip tooltip-bottom text-left"
          data-tip={violation.rule_content}
        >
          规则 {violation.rule_id}:{" "}
          {violation.rule_content.length > 40
            ? violation.rule_content.slice(0, 40) + "..."
            : violation.rule_content}
        </div>

        {/* 人工二审操作区 */}
        <div className="border-t border-base-200 pt-2 mt-1">
          {isPending ? (
            <div className="flex justify-end gap-1">
              <button
                className="btn btn-success btn-xs gap-1"
                onClick={handleConfirm}
              >
                <Check className="h-3 w-3" />
                确认违规
              </button>
              <button
                className="btn btn-ghost btn-xs gap-1"
                onClick={handleReject}
              >
                <X className="h-3 w-3" />
                误报忽略
              </button>
            </div>
          ) : (
            <div className="flex justify-end">
              <button
                className="btn btn-ghost btn-xs gap-1 text-base-content/40"
                onClick={handleReset}
              >
                <RotateCcw className="h-3 w-3" />
                重新审核
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
