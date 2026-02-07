import { useState } from "react";
import { FileText, ShieldAlert } from "lucide-react";
import { TranscriptToolbar } from "../transcript/TranscriptToolbar";
import { TranscriptList } from "../transcript/TranscriptList";
import { SpeakerRenameModal } from "../transcript/SpeakerRenameModal";
import { ViolationList } from "../compliance/ViolationList";
import { useComplianceStore } from "../../stores/complianceStore";
import { useAuditKeyboard } from "../../hooks/useAuditKeyboard";

type Tab = "transcript" | "violations";

export function RightPanel() {
  const [renameOpen, setRenameOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("transcript");
  const report = useComplianceStore((s) => s.report);

  const violationCount = report?.violations.length ?? 0;
  const hasReport = report !== null;

  useAuditKeyboard(hasReport && activeTab === "violations");

  return (
    <div className="flex flex-col h-full">
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
            <ShieldAlert className="h-4 w-4" />
            违规报告
            {violationCount > 0 && (
              <span className="badge badge-error badge-xs">{violationCount}</span>
            )}
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
