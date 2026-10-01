import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, Pencil, Search, Trash2, X } from "lucide-react";
import { useTaskHistory, type StatusFilterOption } from "../../hooks/useTaskHistory";
import type { TaskStatus, TaskSummary } from "../../types/task";

const IN_PROGRESS = "处理中";

const STATUS_OPTIONS: { value: StatusFilterOption; label: string }[] = [
  { value: "all", label: "全部状态" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "in_progress", label: "处理中" },
];

function statusBadge(status: TaskStatus): { label: string; className: string } {
  if (status === "completed") return { label: "已完成", className: "badge-success" };
  if (status === "failed") return { label: "失败", className: "badge-error" };
  return { label: IN_PROGRESS, className: "badge-info" };
}

function formatCreatedAt(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("zh-CN", { hour12: false });
}

interface RowProps {
  task: TaskSummary;
  onRename: (name: string) => void;
  onDelete: () => void;
}

function TaskRow({ task, onRename, onDelete }: RowProps) {
  const [mode, setMode] = useState<"view" | "rename" | "confirmDelete">("view");
  const [draft, setDraft] = useState(task.name);
  const badge = statusBadge(task.status);

  const commitRename = () => {
    const name = draft.trim();
    if (name && name !== task.name) onRename(name);
    setMode("view");
  };

  return (
    <li className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-base-200 group">
      <div className="flex-1 min-w-0">
        {mode === "rename" ? (
          <input
            autoFocus
            className="input input-bordered input-sm w-full"
            maxLength={100}
            value={draft}
            aria-label="任务名称"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") setMode("view");
            }}
          />
        ) : (
          <Link
            to={`/workspace/${task.task_id}`}
            className="block truncate font-medium hover:text-primary"
            title={task.status === "failed" && task.error ? task.error : task.name}
          >
            {task.name}
          </Link>
        )}
        <div className="text-xs text-base-content/50 flex gap-2">
          <span>{formatCreatedAt(task.created_at)}</span>
          {task.has_video && <span>视频</span>}
          {task.has_compliance && <span>已审核</span>}
        </div>
      </div>

      <span className={`badge badge-sm ${badge.className}`}>{badge.label}</span>

      {mode === "confirmDelete" ? (
        <div className="flex items-center gap-1 text-xs">
          <span className="text-error">彻底删除？</span>
          <button className="btn btn-xs btn-error" onClick={onDelete}>
            删除
          </button>
          <button className="btn btn-xs btn-ghost" onClick={() => setMode("view")}>
            取消
          </button>
        </div>
      ) : mode === "rename" ? (
        <div className="flex gap-1">
          <button className="btn btn-xs btn-ghost" onClick={commitRename} aria-label="保存名称">
            <Check className="h-3.5 w-3.5" />
          </button>
          <button className="btn btn-xs btn-ghost" onClick={() => setMode("view")} aria-label="取消重命名">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : (
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
          <button
            className="btn btn-xs btn-ghost"
            aria-label="重命名"
            onClick={() => {
              setDraft(task.name);
              setMode("rename");
            }}
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            className="btn btn-xs btn-ghost text-error"
            aria-label="删除"
            disabled={task.status !== "completed" && task.status !== "failed"}
            title={task.status === "completed" || task.status === "failed" ? "删除" : "处理中的任务无法删除"}
            onClick={() => setMode("confirmDelete")}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </li>
  );
}

export function TaskHistory() {
  const {
    tasks,
    total,
    loading,
    loadingMore,
    hasMore,
    error,
    search,
    setSearch,
    status,
    setStatus,
    loadMore,
    rename,
    remove,
  } = useTaskHistory();
  const filterActive = search.trim() !== "" || status !== "all";

  if (loading) return null;
  if (error) {
    return <p className="text-xs text-base-content/40">{error}</p>;
  }
  // 从未有过任何任务时整块隐藏；一旦有过任务，筛选出的空结果要能看到搜索框以便清空条件
  if (total === 0 && !filterActive) return null;

  return (
    <section className="w-full max-w-lg" aria-label="历史任务">
      <h2 className="text-sm font-semibold text-base-content/60 mb-2">历史任务</h2>
      <div className="flex gap-2 mb-2">
        <label className="input input-sm input-bordered flex-1 flex items-center gap-2">
          <Search className="h-3.5 w-3.5 text-base-content/40" />
          <input
            type="search"
            placeholder="按名称或文件名搜索"
            className="grow"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="搜索历史任务"
          />
        </label>
        <select
          className="select select-sm select-bordered"
          value={status}
          onChange={(e) => setStatus(e.target.value as StatusFilterOption)}
          aria-label="按状态筛选"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {tasks.length === 0 ? (
        <p className="text-xs text-base-content/40 px-3 py-2">没有匹配的任务</p>
      ) : (
        <ul className="flex flex-col">
          {tasks.map((t) => (
            <TaskRow
              key={t.task_id}
              task={t}
              onRename={(name) => rename(t.task_id, name)}
              onDelete={() => remove(t.task_id)}
            />
          ))}
        </ul>
      )}

      {hasMore && (
        <button
          className="btn btn-sm btn-ghost w-full mt-1"
          disabled={loadingMore}
          onClick={loadMore}
        >
          {loadingMore ? "加载中..." : `加载更多（${tasks.length} / ${total}）`}
        </button>
      )}
    </section>
  );
}
