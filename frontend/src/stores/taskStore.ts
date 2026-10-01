import { create } from "zustand";
import type { TaskStatus, TaskProgress } from "../types/task";

interface TaskState {
  taskId: string | null;
  status: TaskStatus | null;
  progress: TaskProgress;
  error: string | null;
  pollEnabled: boolean;
  isVideoTask: boolean;
  queuePosition: number | null;

  setTask: (taskId: string, status: TaskStatus) => void;
  updateStatus: (status: TaskStatus, progress: TaskProgress, queuePosition?: number | null) => void;
  setError: (error: string) => void;
  setPollEnabled: (enabled: boolean) => void;
  reset: () => void;
}

const initialProgress: TaskProgress = {
  current_chunk: 0,
  total_chunks: 0,
  percent: 0,
};

const VIDEO_STAGE_SET = new Set<TaskStatus>(["extracting_frames", "scanning_visual"]);

export const useTaskStore = create<TaskState>((set) => ({
  taskId: null,
  status: null,
  progress: initialProgress,
  error: null,
  pollEnabled: false,
  isVideoTask: false,
  queuePosition: null,

  setTask: (taskId, status) =>
    set({
      taskId, status, progress: initialProgress, error: null,
      pollEnabled: false, isVideoTask: false, queuePosition: null,
    }),

  updateStatus: (status, progress, queuePosition = null) =>
    set((state) => ({
      status,
      progress,
      isVideoTask: state.isVideoTask || VIDEO_STAGE_SET.has(status),
      queuePosition,
    })),

  setError: (error) => set({ error, status: "failed" }),

  setPollEnabled: (enabled) => set({ pollEnabled: enabled }),

  reset: () =>
    set({
      taskId: null, status: null, progress: initialProgress, error: null,
      pollEnabled: false, isVideoTask: false, queuePosition: null,
    }),
}));
