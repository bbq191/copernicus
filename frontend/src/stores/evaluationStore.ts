import { create } from "zustand";
import type { EvaluationResult } from "../types/evaluation";
import { createAsyncTaskActions, initialAsyncTaskSlice, type AsyncTaskSlice } from "./asyncTaskSlice";

interface EvaluationState extends AsyncTaskSlice {
  evaluation: EvaluationResult | null;

  setEvaluation: (result: EvaluationResult) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setProgress: (percent: number, text: string) => void;
  reset: () => void;
}

const initialState = {
  ...initialAsyncTaskSlice,
  evaluation: null,
};

export const useEvaluationStore = create<EvaluationState>((set) => ({
  ...initialState,
  ...createAsyncTaskActions<EvaluationState>(set),

  setEvaluation: (result) =>
    set({ evaluation: result, error: null, isLoading: false, progress: 100, progressText: "" }),
  reset: () => set(initialState),
}));
