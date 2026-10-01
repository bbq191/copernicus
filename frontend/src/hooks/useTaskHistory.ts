import { useCallback, useEffect, useRef, useState } from "react";
import { listTasks, purgeTask, renameTask } from "../api/task";
import { errorMessage } from "../api/errors";
import { useToastStore } from "../stores/toastStore";
import type { TaskStatusFilter, TaskSummary } from "../types/task";

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;

export type StatusFilterOption = TaskStatusFilter | "all";

/** 历史任务列表：搜索、状态筛选、分页加载，及重命名、删除操作。 */
export function useTaskHistory() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilterOption>("all");

  const load = useCallback(
    async (offset: number, append: boolean) => {
      (append ? setLoadingMore : setLoading)(true);
      try {
        const res = await listTasks({
          limit: PAGE_SIZE,
          offset,
          search: search.trim(),
          status: status === "all" ? undefined : status,
        });
        setTasks((prev) => (append ? [...prev, ...res.tasks] : res.tasks));
        setTotal(res.total);
        setError(null);
      } catch (err) {
        setError(errorMessage(err, "加载历史任务失败"));
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [search, status],
  );

  // 首次加载立即执行；之后搜索关键字/状态筛选变化时防抖重新加载第一页
  const isFirstRun = useRef(true);
  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false;
      void load(0, false);
      return;
    }
    const timer = setTimeout(() => void load(0, false), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [load]);

  const loadMore = useCallback(() => {
    void load(tasks.length, true);
  }, [load, tasks.length]);

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

  return {
    tasks,
    total,
    loading,
    loadingMore,
    hasMore: tasks.length < total,
    error,
    search,
    setSearch,
    status,
    setStatus,
    loadMore,
    rename,
    remove,
  };
}
