import { create } from "zustand";
import type { EvaluationResult } from "../types/evaluation";

interface EvaluationState {
  evaluation: EvaluationResult | null;
  isLoading: boolean;
  error: string | null;

  setEvaluation: (result: EvaluationResult) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useEvaluationStore = create<EvaluationState>((set) => ({
  evaluation: null,
  isLoading: false,
  error: null,

  setEvaluation: (result) => set({ evaluation: result, isLoading: false }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error, isLoading: false }),
}));
