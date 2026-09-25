import { memo } from "react";
import { Clock, Check, X, RotateCcw, ExternalLink } from "lucide-react";
import type { Violation } from "../../types/compliance";
import { resolveEvidenceUrl } from "../../api/task";
import { useComplianceStore } from "../../stores/complianceStore";
import { useTaskStore } from "../../stores/taskStore";
import { useToastStore } from "../../stores/toastStore";
import { formatTime } from "../../utils/formatTime";
import { playViolation } from "../../utils/violationPlayback";
import { EvidenceBlock } from "./EvidenceBlock";
import { STATUS_META, severityMeta, sourceMeta } from "./violationMeta";

interface Props {
  violation: Violation;
  isSelected: boolean;
}

export const ViolationCard = memo(function ViolationCard({ violation, isSelected }: Props) {
  const setViolationStatus = useComplianceStore((s) => s.setViolationStatus);
  const setActiveTab = useComplianceStore((s) => s.setActiveTab);
  const batchMode = useComplianceStore((s) => s.batchMode);
  // 只订阅"本卡片是否被勾选"这个布尔值：勾选别的卡片不会触发本卡片重渲染
  const isChecked = useComplianceStore((s) => s.selectedIds.has(violation.id));
  const selectViolation = useComplianceStore((s) => s.selectViolation);
  const toggleSelect = useComplianceStore((s) => s.toggleSelect);
  const openEvidenceDetail = useComplianceStore((s) => s.openEvidenceDetail);
  const taskId = useTaskStore((s) => s.taskId);

  const config = severityMeta(violation.severity);
  const SeverityIcon = config.icon;
  const isPending = violation.status === "pending";
  const statusConfig = isPending ? null : STATUS_META[violation.status];

  const sourceConfig = sourceMeta(violation.source);
  const SourceIcon = sourceConfig.icon;

  const handleCardClick = () => selectViolation(isSelected ? null : violation);

  const jumpToViolation = () => {
    playViolation(violation);
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
    toggleSelect(violation.id);
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
      onClick={handleCardClick}
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
        {violation.review_note && (
          <p className="text-xs text-base-content/50">备注：{violation.review_note}</p>
        )}

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
});
