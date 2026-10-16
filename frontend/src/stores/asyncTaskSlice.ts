/**
 * 异步任务进度的通用状态片段（isLoading/error/progress/progressText），
 * 被 evaluationStore、complianceStore 复用，避免同一套字段+setter 重复定义。
 */
export interface AsyncTaskSlice {
  isLoading: boolean;
  error: string | null;
  progress: number;
  progressText: string;
}

export const initialAsyncTaskSlice: AsyncTaskSlice = {
  isLoading: false,
  error: null,
  progress: 0,
  progressText: "",
};

export function createAsyncTaskActions<T extends AsyncTaskSlice>(
  set: (partial: Partial<T>) => void,
) {
  return {
    setLoading: (loading: boolean) =>
      set({
        isLoading: loading,
        ...(loading ? { error: null } : {}),
        progress: 0,
        progressText: loading ? "提交中..." : "",
      } as Partial<T>),
    setError: (error: string | null) =>
      set({ error, isLoading: false, progress: 0, progressText: "" } as Partial<T>),
    setProgress: (percent: number, text: string) =>
      set({ progress: percent, progressText: text } as Partial<T>),
  };
}
