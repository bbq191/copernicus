import { useState } from "react";
import {
  Search,
  ShieldAlert,
  Filter,
  Layers,
  X,
  Check,
  CheckCheck,
  ListChecks,
} from "lucide-react";
import {
  useComplianceStore,
  getFilteredViolations,
  violationKey,
} from "../../stores/complianceStore";
import { ViolationCard } from "./ViolationCard";

const SEVERITY_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "high", label: "高", className: "badge-error" },
  { value: "medium", label: "中", className: "badge-warning" },
  { value: "low", label: "低", className: "badge-info" },
] as const;

const STATUS_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待审" },
  { value: "confirmed", label: "已确认", className: "badge-success" },
  { value: "rejected", label: "已忽略", className: "badge-ghost" },
] as const;

const SOURCE_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "transcript", label: "语音", className: "badge-primary" },
  { value: "ocr", label: "OCR", className: "badge-secondary" },
  { value: "vision", label: "视觉", className: "badge-accent" },
] as const;

const KBD_DISMISSED_KEY = "copernicus:kbd-hints-dismissed";

export function ViolationList() {
  const [kbdDismissed, setKbdDismissed] = useState(
    () => localStorage.getItem(KBD_DISMISSED_KEY) === "1",
  );
  const report = useComplianceStore((s) => s.report);
  const severityFilter = useComplianceStore((s) => s.severityFilter);
  const setSeverityFilter = useComplianceStore((s) => s.setSeverityFilter);
  const statusFilter = useComplianceStore((s) => s.statusFilter);
  const setStatusFilter = useComplianceStore((s) => s.setStatusFilter);
  const sourceFilter = useComplianceStore((s) => s.sourceFilter);
  const setSourceFilter = useComplianceStore((s) => s.setSourceFilter);
  const searchQuery = useComplianceStore((s) => s.searchQuery);
  const setSearchQuery = useComplianceStore((s) => s.setSearchQuery);
  const selectedViolation = useComplianceStore((s) => s.selectedViolation);
  const selectViolation = useComplianceStore((s) => s.selectViolation);
  const batchMode = useComplianceStore((s) => s.batchMode);
  const toggleBatchMode = useComplianceStore((s) => s.toggleBatchMode);
  const selectedIds = useComplianceStore((s) => s.selectedIds);
  const selectAll = useComplianceStore((s) => s.selectAll);
  const clearSelection = useComplianceStore((s) => s.clearSelection);
  const batchSetStatus = useComplianceStore((s) => s.batchSetStatus);

  const violations = getFilteredViolations(useComplianceStore.getState());

  if (!report) return null;

  const highCount = report.violations.filter(
    (v) => v.severity === "high",
  ).length;
  const mediumCount = report.violations.filter(
    (v) => v.severity === "medium",
  ).length;
  const pendingCount = report.violations.filter(
    (v) => v.status === "pending",
  ).length;

  const severityCounts = {
    all: report.violations.length,
    high: highCount,
    medium: mediumCount,
    low: report.violations.filter((v) => v.severity === "low").length,
  };

  const sourceCounts = {
    all: report.violations.length,
    transcript: report.violations.filter((v) => v.source === "transcript").length,
    ocr: report.violations.filter((v) => v.source === "ocr").length,
    vision: report.violations.filter((v) => v.source === "vision").length,
  };

  const scoreColor =
    report.compliance_score >= 80
      ? "text-success"
      : report.compliance_score >= 60
        ? "text-warning"
        : "text-error";

  // Count how many of the filtered violations are checked
  const checkedCount = violations.filter((v) =>
    selectedIds.has(violationKey(v)),
  ).length;

  return (
    <div className="flex flex-col h-full">
      {/* Stats Dashboard */}
      <div className="stats stats-horizontal shadow-sm w-full bg-base-200 border-b border-base-300">
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">高风险</div>
          <div className="stat-value text-error text-lg">{highCount}</div>
        </div>
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">疑似</div>
          <div className="stat-value text-warning text-lg">{mediumCount}</div>
        </div>
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">待审</div>
          <div className="stat-value text-info text-lg">{pendingCount}</div>
        </div>
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">合规度</div>
          <div className={`stat-value text-lg ${scoreColor}`}>
            {Math.round(report.compliance_score)}
          </div>
        </div>
      </div>

      {/* Keyboard shortcuts hint */}
      {!kbdDismissed && (
        <div className="flex items-center gap-3 px-3 py-1.5 bg-base-200 border-b border-base-300 text-xs text-base-content/60">
          <span className="flex items-center gap-1">
            <kbd className="kbd kbd-xs">Space</kbd> 播放
          </span>
          <span className="flex items-center gap-1">
            <kbd className="kbd kbd-xs">Enter</kbd> 确认
          </span>
          <span className="flex items-center gap-1">
            <kbd className="kbd kbd-xs">Del</kbd> 忽略
          </span>
          <span className="flex items-center gap-1">
            <kbd className="kbd kbd-xs">&#8593;&#8595;</kbd> 切换
          </span>
          <span className="flex items-center gap-1">
            <kbd className="kbd kbd-xs">B</kbd> 批量
          </span>
          <button
            className="ml-auto btn btn-ghost btn-xs"
            onClick={() => {
              setKbdDismissed(true);
              localStorage.setItem(KBD_DISMISSED_KEY, "1");
            }}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-col gap-2 p-3">
        {/* Severity filter */}
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 opacity-50" />
          <div className="flex gap-1">
            {SEVERITY_OPTIONS.map((opt) => {
              const count =
                severityCounts[opt.value as keyof typeof severityCounts];
              return (
                <button
                  key={opt.value}
                  className={`badge badge-sm cursor-pointer ${
                    severityFilter === opt.value
                      ? "className" in opt
                        ? opt.className
                        : "badge-primary"
                      : "badge-ghost"
                  }`}
                  onClick={() =>
                    setSeverityFilter(
                      opt.value as "all" | "high" | "medium" | "low",
                    )
                  }
                >
                  {opt.label}
                  {count > 0 && ` (${count})`}
                </button>
              );
            })}
          </div>
        </div>

        {/* Source filter */}
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 opacity-50" />
          <div className="flex gap-1">
            {SOURCE_OPTIONS.map((opt) => {
              const count =
                sourceCounts[opt.value as keyof typeof sourceCounts];
              return (
                <button
                  key={opt.value}
                  className={`badge badge-sm cursor-pointer ${
                    sourceFilter === opt.value
                      ? "className" in opt
                        ? opt.className
                        : "badge-primary"
                      : "badge-ghost"
                  }`}
                  onClick={() =>
                    setSourceFilter(
                      opt.value as "all" | "transcript" | "ocr" | "vision",
                    )
                  }
                >
                  {opt.label}
                  {count > 0 && ` (${count})`}
                </button>
              );
            })}
          </div>
        </div>

        {/* Status filter + search + batch toggle */}
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 opacity-50" />
          <div className="flex gap-1">
            {STATUS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                className={`badge badge-sm cursor-pointer ${
                  statusFilter === opt.value
                    ? "className" in opt
                      ? opt.className
                      : "badge-primary"
                    : "badge-ghost"
                }`}
                onClick={() =>
                  setStatusFilter(
                    opt.value as "all" | "pending" | "confirmed" | "rejected",
                  )
                }
              >
                {opt.label}
              </button>
            ))}
          </div>

          <button
            className={`btn btn-xs gap-1 ml-2 ${batchMode ? "btn-primary" : "btn-ghost"}`}
            onClick={toggleBatchMode}
          >
            <ListChecks className="h-3.5 w-3.5" />
            批量
          </button>

          <label className="input input-sm input-bordered flex items-center gap-2 w-48 ml-auto">
            <Search className="h-4 w-4 opacity-50" />
            <input
              type="text"
              placeholder="搜索违规..."
              className="grow bg-transparent outline-none"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </label>
        </div>
      </div>

      {/* Violation cards */}
      <div className="flex-1 overflow-y-auto p-3 pt-0 flex flex-col gap-2">
        {violations.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-base-content/40">
            <ShieldAlert className="h-12 w-12 mb-2 opacity-20" />
            <p className="text-sm">
              {report.violations.length === 0
                ? "未发现违规内容"
                : "没有匹配的违规记录"}
            </p>
          </div>
        ) : (
          violations.map((v, i) => (
            <ViolationCard
              key={`${v.timestamp_ms}-${v.rule_id}-${i}`}
              violation={v}
              isSelected={selectedViolation === v}
              onClick={() =>
                selectViolation(selectedViolation === v ? null : v)
              }
            />
          ))
        )}
      </div>

      {/* Batch action bar */}
      {batchMode && (
        <div className="flex items-center gap-3 px-4 py-2 bg-base-200 border-t border-base-300 shrink-0">
          <span className="text-sm font-medium">
            已选 {checkedCount} 项
          </span>
          <button className="btn btn-ghost btn-xs gap-1" onClick={selectAll}>
            <CheckCheck className="h-3 w-3" />
            全选
          </button>
          <button className="btn btn-ghost btn-xs gap-1" onClick={clearSelection}>
            <X className="h-3 w-3" />
            取消
          </button>
          <div className="ml-auto flex gap-2">
            <button
              className="btn btn-success btn-sm gap-1"
              disabled={checkedCount === 0}
              onClick={() => batchSetStatus("confirmed")}
            >
              <Check className="h-3.5 w-3.5" />
              批量确认
            </button>
            <button
              className="btn btn-ghost btn-sm gap-1"
              disabled={checkedCount === 0}
              onClick={() => batchSetStatus("rejected")}
            >
              <X className="h-3.5 w-3.5" />
              批量忽略
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
