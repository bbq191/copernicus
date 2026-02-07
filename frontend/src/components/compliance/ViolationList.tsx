import { Search, ShieldAlert, Filter } from "lucide-react";
import {
  useComplianceStore,
  getFilteredViolations,
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

export function ViolationList() {
  const report = useComplianceStore((s) => s.report);
  const severityFilter = useComplianceStore((s) => s.severityFilter);
  const setSeverityFilter = useComplianceStore((s) => s.setSeverityFilter);
  const statusFilter = useComplianceStore((s) => s.statusFilter);
  const setStatusFilter = useComplianceStore((s) => s.setStatusFilter);
  const searchQuery = useComplianceStore((s) => s.searchQuery);
  const setSearchQuery = useComplianceStore((s) => s.setSearchQuery);
  const selectedViolation = useComplianceStore((s) => s.selectedViolation);
  const selectViolation = useComplianceStore((s) => s.selectViolation);

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

  const scoreColor =
    report.compliance_score >= 80
      ? "text-success"
      : report.compliance_score >= 60
        ? "text-warning"
        : "text-error";

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

        {/* Status filter + search */}
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
    </div>
  );
}
