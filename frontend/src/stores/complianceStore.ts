import { create } from "zustand";
import type {
  ComplianceReport,
  ComplianceRule,
  Violation,
  ViolationSource,
  ViolationStatus,
} from "../types/compliance";
import { persistViolationStatuses } from "../api/compliance";

// ---------------------------------------------------------------------------
// Debounced persistence: batch status changes within 500ms into one API call
// ---------------------------------------------------------------------------
let persistTimer: ReturnType<typeof setTimeout> | undefined;
let pendingUpdates: Map<number, string> = new Map();

function schedulePersist(index: number, status: string) {
  pendingUpdates.set(index, status);
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    const updates = Array.from(pendingUpdates, ([i, s]) => ({ index: i, status: s }));
    pendingUpdates = new Map();
    // Obtain taskId from taskStore (avoid circular import via lazy import)
    import("./taskStore").then(({ useTaskStore }) => {
      const taskId = useTaskStore.getState().taskId;
      if (taskId) persistViolationStatuses(taskId, updates);
    });
  }, 500);
}

// ---------------------------------------------------------------------------
// Violation unique key helper
// ---------------------------------------------------------------------------
function violationKey(v: Violation): string {
  return `${v.timestamp_ms}-${v.rule_id}`;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type SeverityFilter = "all" | "high" | "medium" | "low";
type StatusFilter = "all" | "pending" | "confirmed" | "rejected";
type SourceFilter = "all" | ViolationSource;

export type RightTab = "transcript" | "violations";

interface ComplianceState {
  report: ComplianceReport | null;
  rules: ComplianceRule[] | null;
  isLoading: boolean;
  error: string | null;
  progress: number;
  progressText: string;
  selectedViolation: Violation | null;
  selectedIndex: number;
  severityFilter: SeverityFilter;
  statusFilter: StatusFilter;
  sourceFilter: SourceFilter;
  searchQuery: string;
  activeTab: RightTab;

  // Batch operations
  selectedIds: Set<string>;
  batchMode: boolean;

  // Evidence detail panel
  evidenceDetail: Violation | null;
  evidencePanelOpen: boolean;

  // --- Actions ---
  setReport: (report: ComplianceReport, rules: ComplianceRule[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setProgress: (percent: number, text: string) => void;
  selectViolation: (v: Violation | null) => void;
  setSeverityFilter: (filter: SeverityFilter) => void;
  setStatusFilter: (filter: StatusFilter) => void;
  setSourceFilter: (filter: SourceFilter) => void;
  setSearchQuery: (q: string) => void;
  setViolationStatus: (v: Violation, status: ViolationStatus) => void;
  navigateViolation: (direction: "prev" | "next") => void;
  setActiveTab: (tab: RightTab) => void;

  // Batch actions
  toggleBatchMode: () => void;
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  clearSelection: () => void;
  batchSetStatus: (status: ViolationStatus) => void;

  // Evidence detail actions
  openEvidenceDetail: (v: Violation) => void;
  closeEvidenceDetail: () => void;

  reset: () => void;
}

export const useComplianceStore = create<ComplianceState>((set, get) => ({
  report: null,
  rules: null,
  isLoading: false,
  error: null,
  progress: 0,
  progressText: "",
  selectedViolation: null,
  selectedIndex: -1,
  severityFilter: "all",
  statusFilter: "all",
  sourceFilter: "all",
  searchQuery: "",
  activeTab: "transcript",
  selectedIds: new Set(),
  batchMode: false,
  evidenceDetail: null,
  evidencePanelOpen: false,

  setReport: (report, rules) => {
    const withStatus: ComplianceReport = {
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
    set({
      report: withStatus,
      rules,
      isLoading: false,
      progress: 100,
      progressText: "",
    });
  },
  setLoading: (loading) =>
    set({
      isLoading: loading,
      progress: 0,
      progressText: loading ? "提交中..." : "",
      error: null,
    }),
  setError: (error) =>
    set({ error, isLoading: false, progress: 0, progressText: "" }),
  setProgress: (percent, text) =>
    set({ progress: percent, progressText: text }),
  selectViolation: (v) => {
    if (!v) {
      set({ selectedViolation: null, selectedIndex: -1 });
      return;
    }
    const filtered = getFilteredViolations(get());
    const index = filtered.indexOf(v);
    set({ selectedViolation: v, selectedIndex: index });
  },
  setSeverityFilter: (filter) => set({ severityFilter: filter }),
  setStatusFilter: (filter) => set({ statusFilter: filter }),
  setSourceFilter: (filter) => set({ sourceFilter: filter }),
  setSearchQuery: (q) => set({ searchQuery: q }),

  setViolationStatus: (v, status) => {
    const { report, selectedViolation } = get();
    if (!report) return;
    let updatedSelected = selectedViolation;
    let changedIndex = -1;
    const violations = report.violations.map((item, i) => {
      if (item === v) {
        changedIndex = i;
        const updated = { ...item, status };
        if (selectedViolation === v) updatedSelected = updated;
        return updated;
      }
      return item;
    });
    set({ report: { ...report, violations }, selectedViolation: updatedSelected });
    if (changedIndex >= 0) {
      schedulePersist(changedIndex, status);
    }
  },

  navigateViolation: (direction) => {
    const state = get();
    const filtered = getFilteredViolations(state);
    if (filtered.length === 0) return;

    let newIndex: number;
    if (direction === "next") {
      newIndex =
        state.selectedIndex < filtered.length - 1
          ? state.selectedIndex + 1
          : 0;
    } else {
      newIndex =
        state.selectedIndex > 0
          ? state.selectedIndex - 1
          : filtered.length - 1;
    }

    set({
      selectedViolation: filtered[newIndex],
      selectedIndex: newIndex,
    });
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  // ---------------------------------------------------------------------------
  // Batch operations
  // ---------------------------------------------------------------------------
  toggleBatchMode: () => {
    const { batchMode } = get();
    set({ batchMode: !batchMode, selectedIds: new Set() });
  },

  toggleSelect: (id) => {
    const { selectedIds } = get();
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    set({ selectedIds: next });
  },

  selectAll: () => {
    const filtered = getFilteredViolations(get());
    const ids = new Set(filtered.map(violationKey));
    set({ selectedIds: ids });
  },

  clearSelection: () => set({ selectedIds: new Set() }),

  batchSetStatus: (status) => {
    const { report, selectedIds } = get();
    if (!report || selectedIds.size === 0) return;

    const violations = report.violations.map((item, i) => {
      if (selectedIds.has(violationKey(item))) {
        schedulePersist(i, status);
        return { ...item, status };
      }
      return item;
    });

    set({
      report: { ...report, violations },
      selectedIds: new Set(),
      batchMode: false,
    });

    // Trigger toast via lazy import to avoid circular dependency
    import("./toastStore").then(({ useToastStore }) => {
      useToastStore.getState().addToast("info", `已批量更新 ${selectedIds.size} 条记录`);
    });
  },

  // ---------------------------------------------------------------------------
  // Evidence detail panel
  // ---------------------------------------------------------------------------
  openEvidenceDetail: (v) => set({ evidenceDetail: v, evidencePanelOpen: true }),
  closeEvidenceDetail: () => set({ evidenceDetail: null, evidencePanelOpen: false }),

  // ---------------------------------------------------------------------------
  // Reset
  // ---------------------------------------------------------------------------
  reset: () =>
    set({
      report: null,
      rules: null,
      isLoading: false,
      error: null,
      progress: 0,
      progressText: "",
      selectedViolation: null,
      selectedIndex: -1,
      severityFilter: "all",
      statusFilter: "all",
      sourceFilter: "all",
      searchQuery: "",
      activeTab: "transcript",
      selectedIds: new Set(),
      batchMode: false,
      evidenceDetail: null,
      evidencePanelOpen: false,
    }),
}));

// ---------------------------------------------------------------------------
// Derived filter helper
// ---------------------------------------------------------------------------
export function getFilteredViolations(state: ComplianceState): Violation[] {
  if (!state.report) return [];
  let violations = state.report.violations;
  if (state.severityFilter !== "all") {
    violations = violations.filter((v) => v.severity === state.severityFilter);
  }
  if (state.statusFilter !== "all") {
    violations = violations.filter((v) => v.status === state.statusFilter);
  }
  if (state.sourceFilter !== "all") {
    violations = violations.filter((v) => v.source === state.sourceFilter);
  }
  if (state.searchQuery.trim()) {
    const q = state.searchQuery.toLowerCase();
    violations = violations.filter(
      (v) =>
        v.reason.toLowerCase().includes(q) ||
        v.original_text.toLowerCase().includes(q) ||
        v.rule_content.toLowerCase().includes(q) ||
        (v.evidence_text?.toLowerCase().includes(q) ?? false),
    );
  }
  return violations;
}

export { violationKey };
