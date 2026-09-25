import { useCallback, useEffect, useState } from "react";
import { listTasks, purgeTask, renameTask } from "../api/task";
import { useToastStore } from "../stores/toastStore";
import type { TaskSummary } from "../types/task";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/** 历史任务列表及其重命名、删除操作。 */
export function useTaskHistory() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const res = await listTasks();
      setTasks(res.tasks);
      setTotal(res.total);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "加载历史任务失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const rename = useCallback(
    async (taskId: string, name: string) => {
      try {
        await renameTask(taskId, name);
        setTasks((prev) => prev.map((t) => (t.task_id === taskId ? { ...t, name } : t)));
      } catch (err) {
        useToastStore.getState().addToast("error", errorMessage(err, "重命名失败"));
      }
    },
    [],
  );

  const remove = useCallback(
    async (taskId: string) => {
      try {
        await purgeTask(taskId);
        setTasks((prev) => prev.filter((t) => t.task_id !== taskId));
        setTotal((n) => Math.max(0, n - 1));
      } catch (err) {
        useToastStore.getState().addToast("error", errorMessage(err, "删除失败"));
      }
    },
    [],
  );

  return { tasks, total, loading, error, reload, rename, remove };
}
