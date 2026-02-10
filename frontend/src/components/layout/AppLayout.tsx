import { ThemeToggle } from "../shared/ThemeToggle";
import { LeftPanel } from "./LeftPanel";
import { RightPanel } from "./RightPanel";
import { EvidenceDetailPanel } from "../compliance/EvidenceDetailPanel";
import { useComplianceStore } from "../../stores/complianceStore";
import { useNavigate } from "react-router-dom";

export function AppLayout() {
  const navigate = useNavigate();
  const evidencePanelOpen = useComplianceStore((s) => s.evidencePanelOpen);

  return (
    <div className="flex flex-col h-screen">
      {/* Navbar */}
      <div className="navbar bg-base-100 border-b border-base-300 px-4 min-h-12">
        <div className="flex-1">
          <button
            className="btn btn-ghost text-xl"
            onClick={() => navigate("/")}
          >
            Copernicus
          </button>
        </div>
        <div className="flex-none">
          <ThemeToggle />
        </div>
      </div>

      {/* Three-column body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: media player + summary + compliance config */}
        <div className="w-[420px] shrink-0">
          <LeftPanel />
        </div>

        {/* Center: audit list (main workspace) */}
        <div className="flex-1 min-w-0">
          <RightPanel />
        </div>

        {/* Right: evidence detail (conditional) */}
        {evidencePanelOpen && (
          <div className="w-[380px] shrink-0 border-l border-base-300 overflow-y-auto">
            <EvidenceDetailPanel />
          </div>
        )}
      </div>
    </div>
  );
}
