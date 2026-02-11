import {
  Clock,
  AlertTriangle,
  AlertCircle,
  Info,
  Check,
  X,
  RotateCcw,
  Mic,
  FileText,
  Eye,
  ExternalLink,
} from "lucide-react";
import type { Violation } from "../../types/compliance";
import { resolveEvidenceUrl } from "../../api/task";
import { usePlayerStore } from "../../stores/playerStore";
import {
  useComplianceStore,
  violationKey,
} from "../../stores/complianceStore";
import { useTaskStore } from "../../stores/taskStore";
import { useToastStore } from "../../stores/toastStore";
import { formatTime } from "../../utils/formatTime";
import { EvidenceBlock } from "./EvidenceBlock";

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

const SOURCE_CONFIG = {
  transcript: { badge: "badge-primary", label: "语音", icon: Mic },
  ocr: { badge: "badge-secondary", label: "OCR", icon: FileText },
  vision: { badge: "badge-accent", label: "视觉", icon: Eye },
} as const;

const LOOP_PADDING_MS = 10000;

export function ViolationCard({ violation, isSelected, onClick }: Props) {
  const seekAndPlay = usePlayerStore((s) => s.seekAndPlay);
  const setLoopRegion = usePlayerStore((s) => s.setLoopRegion);
  const setViolationStatus = useComplianceStore((s) => s.setViolationStatus);
  const setActiveTab = useComplianceStore((s) => s.setActiveTab);
  const batchMode = useComplianceStore((s) => s.batchMode);
  const selectedIds = useComplianceStore((s) => s.selectedIds);
  const toggleSelect = useComplianceStore((s) => s.toggleSelect);
  const openEvidenceDetail = useComplianceStore((s) => s.openEvidenceDetail);
  const taskId = useTaskStore((s) => s.taskId);

  const config = SEVERITY_CONFIG[violation.severity] || SEVERITY_CONFIG.low;
  const SeverityIcon = config.icon;
  const isPending = violation.status === "pending";
  const statusConfig =
    !isPending && violation.status in STATUS_CONFIG
      ? STATUS_CONFIG[violation.status as "confirmed" | "rejected"]
      : null;

  const sourceConfig =
    SOURCE_CONFIG[violation.source] || SOURCE_CONFIG.transcript;
  const SourceIcon = sourceConfig.icon;

  const vKey = violationKey(violation);
  const isChecked = selectedIds.has(vKey);

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
    useToastStore.getState().addToast("info", "已确认违规");
  };

  const handleReject = (e: React.MouseEvent) => {
    e.stopPropagation();
    setViolationStatus(violation, "rejected");
    useToastStore.getState().addToast("info", "已标记为误报");
  };

  const handleReset = (e: React.MouseEvent) => {
    e.stopPropagation();
    setViolationStatus(violation, "pending");
  };

  const handleCheckbox = (e: React.MouseEvent) => {
    e.stopPropagation();
    toggleSelect(vKey);
  };

  const handleOpenDetail = (e: React.MouseEvent) => {
    e.stopPropagation();
    openEvidenceDetail(violation);
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
        {/* Row 1: badges */}
        <div className="flex items-center gap-2 flex-wrap">
          {batchMode && (
            <input
              type="checkbox"
              className="checkbox checkbox-xs checkbox-primary"
              checked={isChecked}
              onClick={handleCheckbox}
              readOnly
            />
          )}

          <button
            className="badge badge-ghost badge-sm gap-1 hover:badge-primary"
            onClick={handleTimestampClick}
          >
            <Clock className="h-3 w-3" />
            {formatTime(violation.timestamp_ms)}
          </button>

          <span className={`badge badge-sm gap-1 ${sourceConfig.badge}`}>
            <SourceIcon className="h-3 w-3" />
            {sourceConfig.label}
          </span>

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

        {/* Row 2: reason */}
        <p className="text-sm">{violation.reason}</p>

        {/* Row 2.5: reasoning (collapsed) */}
        {violation.reasoning && (
          <details className="text-xs bg-base-200/50 rounded px-2 py-1">
            <summary className="cursor-pointer text-base-content/50 hover:text-base-content/70 select-none">
              AI 判定逻辑
            </summary>
            <div className="mt-1.5 text-base-content/60 space-y-0.5 pl-2 border-l border-base-300">
              {violation.reasoning.split(/[。；]/).filter(Boolean).map((step, i) => (
                <p key={i}>{step.trim()}</p>
              ))}
            </div>
          </details>
        )}

        {/* Row 3: evidence block */}
        <EvidenceBlock
          source={violation.source}
          originalText={violation.original_text}
          evidenceUrl={resolveEvidenceUrl(violation.evidence_url, taskId)}
          evidenceText={violation.evidence_text}
          onImageClick={() => openEvidenceDetail(violation)}
        />

        {/* Row 4: rule reference */}
        <div className="flex items-center gap-2">
          <div
            className="text-xs text-base-content/40 tooltip tooltip-bottom text-left flex-1"
            data-tip={violation.rule_content}
          >
            规则 {violation.rule_id}
            {violation.rule_ref && (
              <span className="text-base-content/60 font-medium">
                {" "}({violation.rule_ref})
              </span>
            )}
            :{" "}
            {violation.rule_content.length > 40
              ? violation.rule_content.slice(0, 40) + "..."
              : violation.rule_content}
          </div>

          {(violation.evidence_url || violation.evidence_text) && (
            <button
              className="btn btn-ghost btn-xs gap-0.5 text-base-content/40"
              onClick={handleOpenDetail}
            >
              <ExternalLink className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Row 5: actions */}
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
