import { create } from "zustand";
import type {
  ComplianceReport,
  ComplianceRule,
  Violation,
  ViolationStatus,
} from "../types/compliance";
import { persistViolationStatuses } from "../api/compliance";

// Debounced persistence: batch status changes within 500ms into one API call
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

type SeverityFilter = "all" | "high" | "medium" | "low";
type StatusFilter = "all" | "pending" | "confirmed" | "rejected";

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
  searchQuery: string;
  activeTab: RightTab;

  setReport: (report: ComplianceReport, rules: ComplianceRule[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setProgress: (percent: number, text: string) => void;
  selectViolation: (v: Violation | null) => void;
  setSeverityFilter: (filter: SeverityFilter) => void;
  setStatusFilter: (filter: StatusFilter) => void;
  setSearchQuery: (q: string) => void;
  setViolationStatus: (v: Violation, status: ViolationStatus) => void;
  navigateViolation: (direction: "prev" | "next") => void;
  setActiveTab: (tab: RightTab) => void;
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
  searchQuery: "",
  activeTab: "transcript",

  setReport: (report, rules) => {
    const withStatus: ComplianceReport = {
      ...report,
      violations: report.violations.map((v) => ({
        ...v,
        status: v.status || ("pending" as const),
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
      searchQuery: "",
      activeTab: "transcript",
    }),
}));

export function getFilteredViolations(state: ComplianceState): Violation[] {
  if (!state.report) return [];
  let violations = state.report.violations;
  if (state.severityFilter !== "all") {
    violations = violations.filter((v) => v.severity === state.severityFilter);
  }
  if (state.statusFilter !== "all") {
    violations = violations.filter((v) => v.status === state.statusFilter);
  }
  if (state.searchQuery.trim()) {
    const q = state.searchQuery.toLowerCase();
    violations = violations.filter(
      (v) =>
        v.reason.toLowerCase().includes(q) ||
        v.original_text.toLowerCase().includes(q) ||
        v.rule_content.toLowerCase().includes(q),
    );
  }
  return violations;
}
