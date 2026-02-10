import { useState } from "react";
import { FileText, ShieldAlert } from "lucide-react";
import { TranscriptToolbar } from "../transcript/TranscriptToolbar";
import { TranscriptList } from "../transcript/TranscriptList";
import { SpeakerRenameModal } from "../transcript/SpeakerRenameModal";
import { ViolationList } from "../compliance/ViolationList";
import { useComplianceStore } from "../../stores/complianceStore";
import { useAuditKeyboard } from "../../hooks/useAuditKeyboard";

export function RightPanel() {
  const [renameOpen, setRenameOpen] = useState(false);
  const activeTab = useComplianceStore((s) => s.activeTab);
  const setActiveTab = useComplianceStore((s) => s.setActiveTab);
  const report = useComplianceStore((s) => s.report);

  const violationCount = report?.violations.length ?? 0;
  const pendingCount =
    report?.violations.filter((v) => v.status === "pending").length ?? 0;
  const hasReport = report !== null;

  useAuditKeyboard(hasReport && activeTab === "violations");

  return (
    <div className="flex flex-col h-full border-r border-base-300">
      {hasReport && (
        <div role="tablist" className="tabs tabs-bordered px-3 pt-2">
          <button
            role="tab"
            className={`tab gap-1 ${activeTab === "transcript" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("transcript")}
          >
            <FileText className="h-4 w-4" />
            转写结果
          </button>
          <button
            role="tab"
            className={`tab gap-1 ${activeTab === "violations" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("violations")}
          >
            {violationCount > 0 ? (
              <span className="indicator">
                <span className="indicator-item badge badge-error badge-xs">
                  {pendingCount > 0 ? pendingCount : violationCount}
                </span>
                <ShieldAlert className="h-4 w-4" />
              </span>
            ) : (
              <ShieldAlert className="h-4 w-4" />
            )}
            违规报告
          </button>
        </div>
      )}

      {activeTab === "transcript" || !hasReport ? (
        <>
          <TranscriptToolbar onOpenRename={() => setRenameOpen(true)} />
          <div className="flex-1 overflow-hidden">
            <TranscriptList />
          </div>
          <SpeakerRenameModal
            open={renameOpen}
            onClose={() => setRenameOpen(false)}
          />
        </>
      ) : (
        <ViolationList />
      )}
    </div>
  );
}
