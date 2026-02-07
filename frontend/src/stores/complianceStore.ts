import { create } from "zustand";
import type {
  ComplianceReport,
  ComplianceRule,
  Violation,
  ViolationStatus,
} from "../types/compliance";

type SeverityFilter = "all" | "high" | "medium" | "low";
type StatusFilter = "all" | "pending" | "confirmed" | "rejected";

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

  setReport: (report, rules) => {
    const withStatus: ComplianceReport = {
      ...report,
      violations: report.violations.map((v) => ({
        ...v,
        status: "pending" as const,
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
    const violations = report.violations.map((item) => {
      if (item === v) {
        const updated = { ...item, status };
        if (selectedViolation === v) updatedSelected = updated;
        return updated;
      }
      return item;
    });
    set({ report: { ...report, violations }, selectedViolation: updatedSelected });
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
