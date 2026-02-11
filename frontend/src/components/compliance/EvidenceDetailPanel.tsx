import {
  X,
  Check,
  RotateCcw,
  AlertTriangle,
  AlertCircle,
  Info,
  Mic,
  FileText,
  Eye,
  Clock,
  BookOpen,
  ZoomIn,
} from "lucide-react";
import { useState } from "react";
import { resolveEvidenceUrl } from "../../api/task";
import { useComplianceStore } from "../../stores/complianceStore";
import { useTaskStore } from "../../stores/taskStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { usePlayerStore } from "../../stores/playerStore";
import { useToastStore } from "../../stores/toastStore";
import { formatTime } from "../../utils/formatTime";
import type { ViolationSource } from "../../types/compliance";

const SEVERITY_CONFIG = {
  high: { icon: AlertTriangle, label: "高风险", color: "text-error" },
  medium: { icon: AlertCircle, label: "中风险", color: "text-warning" },
  low: { icon: Info, label: "低风险", color: "text-info" },
} as const;

const SOURCE_LABELS: Record<ViolationSource, { label: string; icon: typeof Mic }> = {
  transcript: { label: "语音转录", icon: Mic },
  ocr: { label: "OCR 文字识别", icon: FileText },
  vision: { label: "视觉检测", icon: Eye },
};

const CONTEXT_RANGE = 3;

export function EvidenceDetailPanel() {
  const violation = useComplianceStore((s) => s.evidenceDetail);
  const closeEvidenceDetail = useComplianceStore((s) => s.closeEvidenceDetail);
  const setViolationStatus = useComplianceStore((s) => s.setViolationStatus);
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const seekAndPlay = usePlayerStore((s) => s.seekAndPlay);
  const taskId = useTaskStore((s) => s.taskId);
  const [imageZoom, setImageZoom] = useState(false);

  if (!violation) return null;

  const imageUrl = resolveEvidenceUrl(violation.evidence_url, taskId);

  const sevConfig = SEVERITY_CONFIG[violation.severity] || SEVERITY_CONFIG.low;
  const SevIcon = sevConfig.icon;
  const sourceInfo = SOURCE_LABELS[violation.source] || SOURCE_LABELS.transcript;
  const SourceIcon = sourceInfo.icon;
  const isPending = violation.status === "pending";

  // Find surrounding transcript entries for context
  const contextEntries = (() => {
    if (violation.source !== "transcript" || rawEntries.length === 0) return [];
    const targetIdx = rawEntries.findIndex(
      (e) => e.timestamp_ms === violation.timestamp_ms,
    );
    if (targetIdx === -1) return [];
    const start = Math.max(0, targetIdx - CONTEXT_RANGE);
    const end = Math.min(rawEntries.length, targetIdx + CONTEXT_RANGE + 1);
    return rawEntries.slice(start, end).map((e) => ({
      ...e,
      isCurrent: e.timestamp_ms === violation.timestamp_ms,
    }));
  })();

  const handleConfirm = () => {
    setViolationStatus(violation, "confirmed");
    useToastStore.getState().addToast("info", "已确认违规");
  };

  const handleReject = () => {
    setViolationStatus(violation, "rejected");
    useToastStore.getState().addToast("info", "已标记为误报");
  };

  const handleReset = () => {
    setViolationStatus(violation, "pending");
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 p-3 border-b border-base-300 bg-base-200">
        <span className={`${sevConfig.color}`}>
          <SevIcon className="h-4 w-4" />
        </span>
        <span className="text-sm font-bold flex-1">{sevConfig.label}</span>
        <span className="badge badge-sm badge-ghost">
          {violation.status === "pending"
            ? "待审"
            : violation.status === "confirmed"
              ? "已确认"
              : "已忽略"}
        </span>
        <button
          className="btn btn-ghost btn-xs btn-square"
          onClick={closeEvidenceDetail}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {/* Source + timestamp */}
        <div className="flex items-center gap-2 text-sm text-base-content/60">
          <SourceIcon className="h-4 w-4" />
          <span>{sourceInfo.label}</span>
          <button
            className="badge badge-ghost badge-sm gap-1 hover:badge-primary"
            onClick={() => seekAndPlay(violation.timestamp_ms)}
          >
            <Clock className="h-3 w-3" />
            {formatTime(violation.timestamp_ms)}
          </button>
          {violation.speaker && (
            <span className="badge badge-ghost badge-sm">{violation.speaker}</span>
          )}
          <span className="text-xs ml-auto">
            {Math.round(violation.confidence * 100)}%
          </span>
        </div>

        {/* Reason */}
        <div>
          <h4 className="text-xs font-bold text-base-content/50 mb-1">违规原因</h4>
          <p className="text-sm">{violation.reason}</p>
        </div>

        {/* AI Reasoning */}
        {violation.reasoning && (
          <div>
            <h4 className="text-xs font-bold text-base-content/50 mb-1">AI 判定逻辑</h4>
            <div className="bg-base-200 rounded p-3 text-sm border border-base-300 space-y-1">
              {violation.reasoning.split(/[。；]/).filter(Boolean).map((step, i) => (
                <p key={i} className="text-base-content/70">
                  <span className="text-base-content/40 mr-1">{i + 1}.</span>
                  {step.trim()}
                </p>
              ))}
            </div>
          </div>
        )}

        {/* Screenshot viewer (ocr / vision) */}
        {imageUrl && (
          <div>
            <h4 className="text-xs font-bold text-base-content/50 mb-1">证据截图</h4>
            <div className="relative">
              <img
                src={imageUrl}
                alt="证据截图"
                className="w-full rounded border border-base-300 cursor-pointer hover:opacity-90 transition-opacity"
                onClick={() => setImageZoom(true)}
                loading="lazy"
              />
              <button
                className="absolute top-1 right-1 btn btn-xs btn-circle btn-ghost bg-base-100/80"
                onClick={() => setImageZoom(true)}
              >
                <ZoomIn className="h-3 w-3" />
              </button>
            </div>
          </div>
        )}

        {/* OCR full text */}
        {violation.evidence_text && (
          <div>
            <h4 className="text-xs font-bold text-base-content/50 mb-1">OCR 识别文本</h4>
            <div className="bg-base-200 rounded p-3 text-sm whitespace-pre-wrap border border-base-300">
              {violation.evidence_text}
            </div>
          </div>
        )}

        {/* Original text */}
        {violation.original_text && (
          <div>
            <h4 className="text-xs font-bold text-base-content/50 mb-1">原始文本</h4>
            <blockquote className="text-sm text-base-content/70 border-l-2 border-primary/30 pl-3 italic">
              {violation.original_text}
            </blockquote>
          </div>
        )}

        {/* Rule reference */}
        <div>
          <h4 className="text-xs font-bold text-base-content/50 mb-1 flex items-center gap-1">
            <BookOpen className="h-3 w-3" />
            规则引用
          </h4>
          <div className="bg-base-200 rounded p-3 text-sm border border-base-300">
            <div className="font-medium mb-1">
              规则 {violation.rule_id}
              {violation.rule_ref && (
                <span className="text-primary"> ({violation.rule_ref})</span>
              )}
            </div>
            <p className="text-base-content/70">{violation.rule_content}</p>
          </div>
        </div>

        {/* Transcript context */}
        {contextEntries.length > 0 && (
          <div>
            <h4 className="text-xs font-bold text-base-content/50 mb-1">转录上下文</h4>
            <div className="flex flex-col gap-1">
              {contextEntries.map((entry) => (
                <div
                  key={entry.timestamp_ms}
                  className={`text-xs px-2 py-1 rounded ${
                    entry.isCurrent
                      ? "bg-error/10 border border-error/20 font-medium"
                      : "text-base-content/50"
                  }`}
                >
                  <span className="text-base-content/40 mr-1.5">
                    [{formatTime(entry.timestamp_ms)}]
                  </span>
                  <span className="font-medium mr-1">{entry.speaker}:</span>
                  {entry.text_corrected || entry.text}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Action bar */}
      <div className="p-3 border-t border-base-300 shrink-0">
        {isPending ? (
          <div className="flex gap-2">
            <button
              className="btn btn-success btn-sm flex-1 gap-1"
              onClick={handleConfirm}
            >
              <Check className="h-4 w-4" />
              确认违规
            </button>
            <button
              className="btn btn-ghost btn-sm flex-1 gap-1"
              onClick={handleReject}
            >
              <X className="h-4 w-4" />
              误报忽略
            </button>
          </div>
        ) : (
          <button
            className="btn btn-ghost btn-sm w-full gap-1"
            onClick={handleReset}
          >
            <RotateCcw className="h-4 w-4" />
            重新审核
          </button>
        )}
      </div>

      {/* Image zoom modal */}
      {imageZoom && imageUrl && (
        <dialog className="modal modal-open" onClick={() => setImageZoom(false)}>
          <div className="modal-box max-w-4xl p-2" onClick={(e) => e.stopPropagation()}>
            <img
              src={imageUrl}
              alt="证据截图（放大）"
              className="w-full rounded"
            />
          </div>
          <div className="modal-backdrop" onClick={() => setImageZoom(false)} />
        </dialog>
      )}
    </div>
  );
}
