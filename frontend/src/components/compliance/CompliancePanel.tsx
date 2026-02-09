import { useCallback, useRef } from "react";
import { Upload, ShieldCheck, AlertTriangle } from "lucide-react";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useComplianceStore } from "../../stores/complianceStore";
import { useTaskStore } from "../../stores/taskStore";
import { auditCompliance } from "../../api/compliance";

export function CompliancePanel() {
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const report = useComplianceStore((s) => s.report);
  const isLoading = useComplianceStore((s) => s.isLoading);
  const error = useComplianceStore((s) => s.error);
  const progress = useComplianceStore((s) => s.progress);
  const progressText = useComplianceStore((s) => s.progressText);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      if (rawEntries.length === 0) return;

      const store = useComplianceStore.getState();
      if (store.isLoading) return;
      store.setLoading(true);

      // Read taskId from store directly to avoid stale closure
      const currentTaskId = useTaskStore.getState().taskId;

      auditCompliance(rawEntries, file, currentTaskId ?? undefined)
        .then((res) => {
          useComplianceStore.getState().setReport(res.report, res.rules);
        })
        .catch((err) => {
          useComplianceStore
            .getState()
            .setError(err instanceof Error ? err.message : "合规审核失败");
        });
    },
    [rawEntries],
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
      e.target.value = "";
    },
    [handleFile],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  if (rawEntries.length === 0) {
    return (
      <div className="p-4 text-base-content/40 text-center text-sm">
        转录完成后可进行合规审核
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-6">
        <span className="loading loading-spinner loading-lg text-primary" />
        <span className="text-base-content/60 text-sm">
          {progressText || "合规审核中..."}
        </span>
        <div className="w-full max-w-xs">
          <progress
            className="progress progress-primary w-full"
            value={progress}
            max={100}
          />
          <span className="text-xs text-base-content/40 mt-1 block text-center">
            {Math.round(progress)}%
          </span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="text-error text-center text-sm mb-2">{error}</div>
        <button
          className="btn btn-sm btn-outline btn-error w-full"
          onClick={() => {
            useComplianceStore.getState().reset();
          }}
        >
          重试
        </button>
      </div>
    );
  }

  if (report) {
    const high = report.violations.filter((v) => v.severity === "high").length;
    const medium = report.violations.filter(
      (v) => v.severity === "medium",
    ).length;
    const low = report.violations.filter((v) => v.severity === "low").length;

    return (
      <div className="flex flex-col gap-3 p-4">
        <h2 className="font-bold text-lg flex items-center gap-2">
          <ShieldCheck className="h-5 w-5" />
          合规审核
        </h2>

        <div className="flex items-center justify-center">
          <div
            className={`radial-progress text-2xl font-bold ${
              report.compliance_score >= 80
                ? "text-success"
                : report.compliance_score >= 60
                  ? "text-warning"
                  : "text-error"
            }`}
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
      <h2 className="font-bold text-lg flex items-center gap-2">
        <ShieldCheck className="h-5 w-5" />
        合规审核
      </h2>
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
    </div>
  );
}
