import { Link } from "react-router-dom";
import { Upload, AlertTriangle, ListChecks } from "lucide-react";
import { IncompleteNotice } from "../shared/IncompleteNotice";
import { reportIncompleteness } from "../../utils/completeness";
import { useComplianceStore } from "../../stores/complianceStore";
import { useComplianceAudit } from "../../hooks/useComplianceAudit";
import { ErrorAlert } from "../shared/ErrorAlert";
import { ProgressBlock } from "../shared/ProgressBlock";
import { scoreLevel, summarizeViolations } from "../../utils/violationFilters";

export function CompliancePanel() {
  const { rawEntries, report, isLoading, error, progress, progressText, fileRef, submit, onFileChange, onDrop } =
    useComplianceAudit();

  if (rawEntries.length === 0) {
    return (
      <div className="p-4 text-base-content/40 text-center text-sm">
        转录完成后可进行合规审核
      </div>
    );
  }

  if (isLoading) {
    return <ProgressBlock text={progressText || "合规审核中..."} percent={progress} />;
  }

  if (error) {
    return (
      <div className="p-4">
        <ErrorAlert
          compact
          message={error}
          onRetry={() => useComplianceStore.getState().reset()}
        />
      </div>
    );
  }

  if (report) {
    const { high, medium, low } = summarizeViolations(report).severity;
    const level = scoreLevel(report.compliance_score);

    return (
      <div className="flex flex-col gap-3 p-4">
        <IncompleteNotice notes={reportIncompleteness(report)} />
        <div className="flex items-center justify-center">
          <div
            className={`radial-progress text-2xl font-bold ${level.text}`}
            style={
              {
                "--value": report.compliance_score,
                "--size": "5rem",
              } as React.CSSProperties
            }
            role="progressbar"
          >
            {Math.round(report.compliance_score)}
          </div>
        </div>

        <div className="text-center text-xs font-medium">
          <span className={level.text}>{level.label}</span>
        </div>

        <div className="flex justify-center gap-2 text-xs">
          {high > 0 && (
            <span className="badge badge-error badge-sm gap-1">
              <AlertTriangle className="h-3 w-3" />
              {high}
            </span>
          )}
          {medium > 0 && (
            <span className="badge badge-warning badge-sm">{medium} 中</span>
          )}
          {low > 0 && (
            <span className="badge badge-info badge-sm">{low} 低</span>
          )}
          {report.violations.length === 0 && (
            <span className="badge badge-success badge-sm">无违规</span>
          )}
        </div>

        <div className="text-xs text-base-content/60">
          共检查 {report.total_rules} 条规则，{report.total_segments_checked}{" "}
          个段落
        </div>

        {report.summary && (
          <>
            <div className="divider my-0" />
            <p className="text-sm">{report.summary}</p>
          </>
        )}

        <div className="divider my-0" />
        <button
          className="btn btn-sm btn-ghost btn-block"
          onClick={() => {
            useComplianceStore.getState().reset();
          }}
        >
          重新审核
        </button>
      </div>
    );
  }

  // 上传规则文件
  return (
    <div className="flex flex-col gap-3 p-4">
      <div
        className="border-2 border-dashed border-base-300 rounded-lg p-4 text-center cursor-pointer hover:border-primary transition-colors"
        onClick={() => fileRef.current?.click()}
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
      >
        <Upload className="h-6 w-6 mx-auto mb-2 opacity-40" />
        <p className="text-sm text-base-content/60">
          上传检查标准文件
        </p>
        <p className="text-xs text-base-content/40 mt-1">
          支持 .csv / .xlsx 格式
        </p>
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx,.xls"
        className="hidden"
        onChange={onFileChange}
      />

      <div className="divider text-xs text-base-content/40 my-0">或</div>

      <button
        className="btn btn-sm btn-outline gap-1.5"
        onClick={() => submit("library")}
      >
        <ListChecks className="h-3.5 w-3.5" />
        使用规则库中的规则
      </button>
      <Link to="/rules" className="text-xs text-base-content/40 hover:text-base-content/70 text-center">
        管理规则库 →
      </Link>
    </div>
  );
}
