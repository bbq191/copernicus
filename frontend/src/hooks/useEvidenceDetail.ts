import { useState } from "react";
import { resolveEvidenceUrl } from "../api/task";
import { useComplianceStore } from "../stores/complianceStore";
import { useTaskStore } from "../stores/taskStore";
import { useTranscriptStore } from "../stores/transcriptStore";
import { usePlayerStore } from "../stores/playerStore";
import { useToastStore } from "../stores/toastStore";
import type { Violation } from "../types/compliance";

const CONTEXT_RANGE = 3;

/** 证据详情面板的数据派生（上下文转写、截图地址）与人工复核操作。 */
export function useEvidenceDetail(violation: Violation) {
  const closeEvidenceDetail = useComplianceStore((s) => s.closeEvidenceDetail);
  const setViolationStatus = useComplianceStore((s) => s.setViolationStatus);
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const seekAndPlay = usePlayerStore((s) => s.seekAndPlay);
  const taskId = useTaskStore((s) => s.taskId);
  const [imageZoom, setImageZoom] = useState(false);
  const [note, setNote] = useState(violation.review_note ?? "");

  const imageUrl = resolveEvidenceUrl(violation.evidence_url, taskId);

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
    setViolationStatus(violation, "confirmed", note);
    useToastStore.getState().addToast("info", "已确认违规");
  };

  const handleReject = () => {
    setViolationStatus(violation, "rejected", note);
    useToastStore.getState().addToast("info", "已标记为误报");
  };

  const handleReset = () => {
    setViolationStatus(violation, "pending");
  };

  return {
    closeEvidenceDetail,
    seekAndPlay,
    imageUrl,
    contextEntries,
    imageZoom,
    setImageZoom,
    note,
    setNote,
    handleConfirm,
    handleReject,
    handleReset,
  };
}
