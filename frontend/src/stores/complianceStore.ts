import { create } from "zustand";
import type {
  ComplianceReport,
  ComplianceRule,
  Violation,
  ViolationStatus,
} from "../types/compliance";
import { persistViolationStatuses } from "../api/compliance";
import {
  filterViolations,
  type SeverityFilter,
  type SourceFilter,
  type StatusFilter,
} from "../utils/violationFilters";
import { ReviewPersister } from "./reviewPersister";
import { useTaskStore } from "./taskStore";
import { useToastStore } from "./toastStore";

// ---------------------------------------------------------------------------
// 复核结果持久化（防抖、按任务绑定、失败重试；细节见 ReviewPersister）
// ---------------------------------------------------------------------------
const persister = new ReviewPersister({
  send: (taskId, updates, options) => persistViolationStatuses(taskId, updates, options),
  onSaved: (taskId, score) => {
    // 评分由服务端按复核结果重算（已驳回的不再扣分）；期间已切换任务则忽略
    if (useTaskStore.getState().taskId !== taskId) return;
    const { report } = useComplianceStore.getState();
    if (report) useComplianceStore.setState({ report: { ...report, compliance_score: score } });
  },
  onError: (willRetry) => {
    useToastStore
      .getState()
      .addToast("error", willRetry ? "复核状态保存失败，稍后将自动重试" : "复核状态多次保存失败，请检查网络后再操作一次以重试");
  },
});

/** 立即提交尚未保存的复核结果（切换任务、关闭页面前调用）。 */
export function flushReviews(options?: { keepalive: boolean }): Promise<void> {
  return persister.flush(options);
}

if (typeof document !== "undefined") {
  // 标签页转入后台或关闭时，防抖窗口内的修改不能丢
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flushReviews({ keepalive: true });
  });
  window.addEventListener("pagehide", () => void flushReviews({ keepalive: true }));
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------
export type RightTab = "transcript" | "violations";

interface ComplianceState {
  report: ComplianceReport | null;
  rules: ComplianceRule[] | null;
  isLoading: boolean;
  error: string | null;
  progress: number;
  progressText: string;

  // 选中项与证据面板只保存 id：违规对象在复核后会被替换成新对象，按 id 才能稳定对应
  selectedId: string | null;
  evidenceDetailId: string | null;

  severityFilter: SeverityFilter;
  statusFilter: StatusFilter;
  sourceFilter: SourceFilter;
  searchQuery: string;
  activeTab: RightTab;

  selectedIds: Set<string>;
  batchMode: boolean;

  setReport: (report: ComplianceReport, rules: ComplianceRule[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setProgress: (percent: number, text: string) => void;
  selectViolation: (v: Violation | null) => void;
  setSeverityFilter: (filter: SeverityFilter) => void;
  setStatusFilter: (filter: StatusFilter) => void;
  setSourceFilter: (filter: SourceFilter) => void;
  setSearchQuery: (q: string) => void;
  setViolationStatus: (v: Violation, status: ViolationStatus, note?: string) => void;
  navigateViolation: (direction: "prev" | "next") => void;
  setActiveTab: (tab: RightTab) => void;

  toggleBatchMode: () => void;
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  clearSelection: () => void;
  batchSetStatus: (status: ViolationStatus) => void;

  openEvidenceDetail: (v: Violation) => void;
  closeEvidenceDetail: () => void;

  reset: () => void;
}

const initialState = {
  report: null,
  rules: null,
  isLoading: false,
  error: null,
  progress: 0,
  progressText: "",
  selectedId: null,
  evidenceDetailId: null,
  severityFilter: "all" as SeverityFilter,
  statusFilter: "all" as StatusFilter,
  sourceFilter: "all" as SourceFilter,
  searchQuery: "",
  activeTab: "transcript" as RightTab,
  batchMode: false,
};

export const useComplianceStore = create<ComplianceState>((set, get) => {
  /** 单条与批量复核共用：更新本地状态（乐观），并把修改交给持久化队列。 */
  const applyReview = (ids: ReadonlySet<string>, status: ViolationStatus, note?: string) => {
    const { report } = get();
    if (!report || ids.size === 0) return;

    const taskId = useTaskStore.getState().taskId;
    // 本地时间仅用于即时显示；持久化后以服务端时间戳为准
    const reviewedAt = status === "pending" ? null : new Date().toISOString();

    const violations = report.violations.map((item) => {
      if (!ids.has(item.id)) return item;
      const reviewNote =
        status === "pending" ? null : (note === undefined ? item.review_note : note.trim()) || null;
      if (taskId) persister.schedule(taskId, { violation_id: item.id, status, note });
      return { ...item, status, reviewed_at: reviewedAt, review_note: reviewNote };
    });
    set({ report: { ...report, violations } });
  };

  return {
    ...initialState,
    selectedIds: new Set(),

    setReport: (report, rules) => {
      const withDefaults: ComplianceReport = {
        ...report,
        violations: report.violations.map((v) => ({
          ...v,
          status: v.status || ("pending" as const),
          source: v.source || ("transcript" as const),
          evidence_url: v.evidence_url ?? null,
          evidence_text: v.evidence_text ?? null,
          rule_ref: v.rule_ref ?? null,
        })),
      };
      set({ report: withDefaults, rules, isLoading: false, progress: 100, progressText: "" });
    },
    setLoading: (loading) =>
      set({ isLoading: loading, progress: 0, progressText: loading ? "提交中..." : "", error: null }),
    setError: (error) => set({ error, isLoading: false, progress: 0, progressText: "" }),
    setProgress: (percent, text) => set({ progress: percent, progressText: text }),

    selectViolation: (v) => set({ selectedId: v?.id ?? null }),
    setSeverityFilter: (filter) => set({ severityFilter: filter }),
    setStatusFilter: (filter) => set({ statusFilter: filter }),
    setSourceFilter: (filter) => set({ sourceFilter: filter }),
    setSearchQuery: (q) => set({ searchQuery: q }),
    setActiveTab: (tab) => set({ activeTab: tab }),

    setViolationStatus: (v, status, note) => applyReview(new Set([v.id]), status, note),

    navigateViolation: (direction) => {
      const filtered = getFilteredViolations(get());
      if (filtered.length === 0) return;

      // 以 id 定位当前项：确认后它可能已被筛选条件排除（index=-1），此时从头/尾开始
      const current = filtered.findIndex((v) => v.id === get().selectedId);
      const last = filtered.length - 1;
      const next =
        direction === "next"
          ? current < 0 || current >= last ? 0 : current + 1
          : current <= 0 ? last : current - 1;
      set({ selectedId: filtered[next].id });
    },

    toggleBatchMode: () => set({ batchMode: !get().batchMode, selectedIds: new Set() }),
    toggleSelect: (id) => {
      const next = new Set(get().selectedIds);
      if (!next.delete(id)) next.add(id);
      set({ selectedIds: next });
    },
    selectAll: () => set({ selectedIds: new Set(getFilteredViolations(get()).map((v) => v.id)) }),
    clearSelection: () => set({ selectedIds: new Set() }),

    batchSetStatus: (status) => {
      const { selectedIds } = get();
      if (selectedIds.size === 0) return;
      const count = selectedIds.size;
      applyReview(selectedIds, status);
      set({ selectedIds: new Set(), batchMode: false });
      useToastStore.getState().addToast("info", `已批量更新 ${count} 条记录`);
    },

    openEvidenceDetail: (v) => set({ evidenceDetailId: v.id }),
    closeEvidenceDetail: () => set({ evidenceDetailId: null }),

    reset: () => {
      persister.discard();
      set({ ...initialState, selectedIds: new Set() });
    },
  };
});

// ---------------------------------------------------------------------------
// 派生数据
// ---------------------------------------------------------------------------
export function getFilteredViolations(state: ComplianceState): Violation[] {
  if (!state.report) return [];
  return filterViolations(state.report.violations, {
    severity: state.severityFilter,
    status: state.statusFilter,
    source: state.sourceFilter,
    query: state.searchQuery,
  });
}

export function selectSelectedViolation(state: ComplianceState): Violation | null {
  return state.report?.violations.find((v) => v.id === state.selectedId) ?? null;
}

export function selectEvidenceDetail(state: ComplianceState): Violation | null {
  return state.report?.violations.find((v) => v.id === state.evidenceDetailId) ?? null;
}
