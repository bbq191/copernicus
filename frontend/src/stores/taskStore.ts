import { create } from "zustand";
import type { TaskStatus, TaskProgress } from "../types/task";

interface TaskState {
  taskId: string | null;
  status: TaskStatus | null;
  progress: TaskProgress;
  error: string | null;
  pollEnabled: boolean;

  setTask: (taskId: string, status: TaskStatus) => void;
  updateStatus: (status: TaskStatus, progress: TaskProgress) => void;
  setError: (error: string) => void;
  setPollEnabled: (enabled: boolean) => void;
  reset: () => void;
}

const initialProgress: TaskProgress = {
  current_chunk: 0,
  total_chunks: 0,
  percent: 0,
};

export const useTaskStore = create<TaskState>((set) => ({
  taskId: null,
  status: null,
  progress: initialProgress,
  error: null,
  pollEnabled: false,

  setTask: (taskId, status) =>
    set({ taskId, status, progress: initialProgress, error: null, pollEnabled: false }),

  updateStatus: (status, progress) => set({ status, progress }),

  setError: (error) => set({ error, status: "failed" }),

  setPollEnabled: (enabled) => set({ pollEnabled: enabled }),

  reset: () =>
    set({ taskId: null, status: null, progress: initialProgress, error: null, pollEnabled: false }),
}));
