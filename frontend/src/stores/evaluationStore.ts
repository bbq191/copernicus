import { create } from "zustand";
import type { EvaluationResult } from "../types/evaluation";

interface EvaluationState {
  evaluation: EvaluationResult | null;
  isLoading: boolean;
  error: string | null;
  progress: number; // 0-100
  progressText: string;

  setEvaluation: (result: EvaluationResult) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setProgress: (percent: number, text: string) => void;
}

export const useEvaluationStore = create<EvaluationState>((set) => ({
  evaluation: null,
  isLoading: false,
  error: null,
  progress: 0,
  progressText: "",

  setEvaluation: (result) =>
    set({ evaluation: result, isLoading: false, progress: 100, progressText: "" }),
  setLoading: (loading) =>
    set({ isLoading: loading, progress: 0, progressText: loading ? "提交中..." : "" }),
  setError: (error) => set({ error, isLoading: false, progress: 0, progressText: "" }),
  setProgress: (percent, text) => set({ progress: percent, progressText: text }),
}));
