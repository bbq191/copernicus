import { create } from "zustand";

interface SynthesisState {
  hasSynthesis: boolean;
  durationMs: number | null;
  synthesisMs: number | null;
  setHasSynthesis: (value: boolean) => void;
  setResult: (durationMs: number, synthesisMs: number) => void;
  reset: () => void;
}

export const useSynthesisStore = create<SynthesisState>((set) => ({
  hasSynthesis: false,
  durationMs: null,
  synthesisMs: null,
  setHasSynthesis: (value) => set({ hasSynthesis: value }),
  setResult: (durationMs, synthesisMs) =>
    set({ hasSynthesis: true, durationMs, synthesisMs }),
  reset: () => set({ hasSynthesis: false, durationMs: null, synthesisMs: null }),
}));
