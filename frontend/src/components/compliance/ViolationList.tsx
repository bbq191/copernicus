import { useMemo, useState } from "react";
import {
  Search,
  ShieldAlert,
  Filter,
  Layers,
  X,
  Check,
  CheckCheck,
  ListChecks,
  Download,
} from "lucide-react";
import { useComplianceStore } from "../../stores/complianceStore";
import { ViolationCard } from "./ViolationCard";
import { FilterChips, type ChipOption } from "./FilterChips";
import { SEVERITY_META, SOURCE_META, STATUS_META } from "./violationMeta";
import {
  filterViolations,
  scoreLevel,
  summarizeViolations,
  type SeverityFilter,
  type SourceFilter,
  type StatusFilter,
} from "../../utils/violationFilters";
import { complianceExportUrl } from "../../api/compliance";
import { useTaskStore } from "../../stores/taskStore";
import { IncompleteNotice } from "../shared/IncompleteNotice";
import { reportIncompleteness } from "../../utils/completeness";
import { readStorage, writeStorage } from "../../utils/safeStorage";

const ALL = { value: "all", label: "全部" } as const;

const SEVERITY_OPTIONS: readonly ChipOption<SeverityFilter>[] = [
  ALL,
  ...(["high", "medium", "low"] as const).map((v) => ({
    value: v,
    label: SEVERITY_META[v].label,
    activeClass: SEVERITY_META[v].badge,
  })),
];

const SOURCE_OPTIONS: readonly ChipOption<SourceFilter>[] = [
  ALL,
  ...(["transcript", "ocr", "vision"] as const).map((v) => ({
    value: v,
    label: SOURCE_META[v].label,
    activeClass: SOURCE_META[v].badge,
  })),
];

const STATUS_OPTIONS: readonly ChipOption<StatusFilter>[] = [
  ALL,
  { value: "pending", label: STATUS_META.pending.label },
  { value: "confirmed", label: STATUS_META.confirmed.label, activeClass: STATUS_META.confirmed.badge },
  { value: "rejected", label: STATUS_META.rejected.label, activeClass: STATUS_META.rejected.badge },
];

const KBD_DISMISSED_KEY = "copernicus:kbd-hints-dismissed";

export function ViolationList() {
  const [kbdDismissed, setKbdDismissed] = useState(() => readStorage(KBD_DISMISSED_KEY) === "1");
  const report = useComplianceStore((s) => s.report);
  const severityFilter = useComplianceStore((s) => s.severityFilter);
  const setSeverityFilter = useComplianceStore((s) => s.setSeverityFilter);
  const statusFilter = useComplianceStore((s) => s.statusFilter);
  const setStatusFilter = useComplianceStore((s) => s.setStatusFilter);
  const sourceFilter = useComplianceStore((s) => s.sourceFilter);
  const setSourceFilter = useComplianceStore((s) => s.setSourceFilter);
  const searchQuery = useComplianceStore((s) => s.searchQuery);
  const setSearchQuery = useComplianceStore((s) => s.setSearchQuery);
  const selectedId = useComplianceStore((s) => s.selectedId);
  const batchMode = useComplianceStore((s) => s.batchMode);
  const toggleBatchMode = useComplianceStore((s) => s.toggleBatchMode);
  const selectedIds = useComplianceStore((s) => s.selectedIds);
  const selectAll = useComplianceStore((s) => s.selectAll);
  const clearSelection = useComplianceStore((s) => s.clearSelection);
  const batchSetStatus = useComplianceStore((s) => s.batchSetStatus);
  const taskId = useTaskStore((s) => s.taskId);

  // 筛选与统计只在报告或筛选条件变化时重算，不随每次渲染重跑
  const violations = useMemo(
    () =>
      filterViolations(report?.violations ?? [], {
        severity: severityFilter,
        status: statusFilter,
        source: sourceFilter,
        query: searchQuery,
      }),
    [report, severityFilter, statusFilter, sourceFilter, searchQuery],
  );
  const summary = useMemo(() => summarizeViolations(report), [report]);

  if (!report) return null;

  const severityCounts = { all: summary.total, ...summary.severity };
  const sourceCounts = { all: summary.total, ...summary.source };
  const checkedCount = violations.filter((v) => selectedIds.has(v.id)).length;

  return (
    <div className="flex flex-col h-full">
      <IncompleteNotice notes={reportIncompleteness(report)} />
      {/* Stats Dashboard */}
      <div className="stats stats-horizontal shadow-sm w-full bg-base-200 border-b border-base-300">
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">高风险</div>
          <div className="stat-value text-error text-lg">{summary.severity.high}</div>
        </div>
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">疑似</div>
          <div className="stat-value text-warning text-lg">{summary.severity.medium}</div>
        </div>
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">待审</div>
          <div className="stat-value text-info text-lg">{summary.status.pending}</div>
        </div>
        <div className="stat place-items-center py-2 px-3">
          <div className="stat-title text-xs">合规度</div>
          <div className={`stat-value text-lg ${scoreLevel(report.compliance_score).text}`}>
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
              writeStorage(KBD_DISMISSED_KEY, "1");
            }}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-col gap-2 p-3">
        <div className="flex items-center gap-2">
          <FilterChips
            icon={ShieldAlert}
            options={SEVERITY_OPTIONS}
            value={severityFilter}
            onChange={setSeverityFilter}
            counts={severityCounts}
          />
        </div>

        <div className="flex items-center gap-2">
          <FilterChips
            icon={Layers}
            options={SOURCE_OPTIONS}
            value={sourceFilter}
            onChange={setSourceFilter}
            counts={sourceCounts}
          />
        </div>

        {/* Status filter + search + batch toggle */}
        <div className="flex items-center gap-2">
          <FilterChips icon={Filter} options={STATUS_OPTIONS} value={statusFilter} onChange={setStatusFilter} />

          <button
            className={`btn btn-xs gap-1 ml-2 ${batchMode ? "btn-primary" : "btn-ghost"}`}
            onClick={toggleBatchMode}
          >
            <ListChecks className="h-3.5 w-3.5" />
            批量
          </button>

          {taskId && (
            <a
              className="btn btn-xs btn-ghost gap-1"
              href={complianceExportUrl(taskId)}
              download
              title="导出 Excel 报告（含复核状态与备注）"
            >
              <Download className="h-3.5 w-3.5" />
              导出
            </a>
          )}

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
          violations.map((v) => (
            <ViolationCard key={v.id} violation={v} isSelected={selectedId === v.id} />
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
