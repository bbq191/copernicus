import { Sparkles, ShieldCheck } from "lucide-react";
import { AudioPlayer } from "../player/AudioPlayer";
import { SummaryPanel } from "../summary/SummaryPanel";
import { CompliancePanel } from "../compliance/CompliancePanel";
import { useEvaluationStore } from "../../stores/evaluationStore";
import { useComplianceStore } from "../../stores/complianceStore";

export function LeftPanel() {
  const evaluation = useEvaluationStore((s) => s.evaluation);
  const report = useComplianceStore((s) => s.report);

  const scoreBadge = evaluation ? `${evaluation.scores.total}分` : null;
  const complianceBadge = report
    ? `${Math.round(report.compliance_score)}分`
    : null;
  const violationCount = report?.violations.length ?? 0;

  return (
    <div className="flex flex-col h-full overflow-y-auto border-r border-base-300">
      <AudioPlayer />

      {/* SummaryPanel collapse */}
      <div className="collapse collapse-arrow border-t border-base-300">
        <input type="checkbox" defaultChecked />
        <div className="collapse-title font-bold text-sm flex items-center gap-2 min-h-0 py-2 px-4">
          <Sparkles className="h-4 w-4 shrink-0" />
          智能摘要
          {scoreBadge && (
            <span className="badge badge-primary badge-sm ml-auto">
              {scoreBadge}
            </span>
          )}
        </div>
        <div className="collapse-content px-0 pb-0">
          <SummaryPanel />
        </div>
      </div>

      {/* CompliancePanel collapse */}
      <div className="collapse collapse-arrow border-t border-base-300">
        <input type="checkbox" defaultChecked />
        <div className="collapse-title font-bold text-sm flex items-center gap-2 min-h-0 py-2 px-4">
          <ShieldCheck className="h-4 w-4 shrink-0" />
          合规审核
          {complianceBadge ? (
            <span className="flex items-center gap-1 ml-auto">
              <span
                className={`badge badge-sm ${
                  report!.compliance_score >= 80
                    ? "badge-success"
                    : report!.compliance_score >= 60
                      ? "badge-warning"
                      : "badge-error"
                }`}
              >
                {complianceBadge}
              </span>
              {violationCount > 0 && (
                <span className="badge badge-error badge-sm">
                  {violationCount}
                </span>
              )}
            </span>
          ) : (
            <span className="text-xs text-base-content/40 ml-auto font-normal">
              待上传规则
            </span>
          )}
        </div>
        <div className="collapse-content px-0 pb-0">
          <CompliancePanel />
        </div>
      </div>
    </div>
  );
}
