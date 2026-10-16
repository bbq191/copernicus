import { Link, useNavigate } from "react-router-dom";
import { RefreshCw, ListTodo, AlertTriangle } from "lucide-react";
import { useTodos } from "../hooks/useTodos";
import { ThemeToggle } from "../components/shared/ThemeToggle";
import { severityMeta } from "../components/compliance/violationMeta";

function formatDueAt(dueAt: string | null): { label: string; overdue: boolean } {
  if (!dueAt) return { label: "无截止时间", overdue: false };
  const date = dueAt.slice(0, 10);
  const overdue = date < new Date().toISOString().slice(0, 10);
  return { label: overdue ? `${date}（已逾期）` : date, overdue };
}

export function TodosPage() {
  const navigate = useNavigate();
  const { assignee, setAssignee, todos, loading, error, refresh } = useTodos();

  return (
    <div className="min-h-screen flex flex-col">
      <div className="navbar bg-base-100 border-b border-base-300 px-4 min-h-12">
        <div className="flex-1">
          <button className="btn btn-ghost text-xl" onClick={() => navigate("/")}>
            Copernicus
          </button>
          <span className="text-base-content/40 ml-1">/ 我的待办</span>
        </div>
        <div className="flex-none gap-2">
          <ThemeToggle />
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 max-w-2xl mx-auto w-full">
        <div className="flex items-center justify-between gap-2 flex-wrap mb-6">
          <div className="flex items-center gap-2">
            <ListTodo className="h-5 w-5" />
            <h1 className="text-xl font-semibold">我的待办</h1>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              className="input input-bordered input-sm w-36"
              placeholder="你的姓名"
              aria-label="你的姓名"
              maxLength={50}
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            />
            <button
              className="btn btn-ghost btn-sm btn-square"
              onClick={refresh}
              disabled={loading}
              title="刷新"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {!assignee.trim() && (
          <p className="text-sm text-base-content/40 text-center py-16">
            填写你的姓名，查看指派给你的待处理违规
          </p>
        )}

        {error && (
          <div className="alert alert-error mb-4">
            <span className="text-sm">{error}</span>
          </div>
        )}

        {assignee.trim() && !error && !loading && todos.length === 0 && (
          <p className="text-sm text-base-content/40 text-center py-16">暂无待办</p>
        )}

        <ul className="flex flex-col gap-2">
          {todos.map((item) => {
            const due = formatDueAt(item.due_at);
            const sev = severityMeta(item.severity);
            return (
              <li key={`${item.task_id}-${item.id}`}>
                <Link
                  to={`/workspace/${item.task_id}`}
                  className="card bg-base-100 border border-base-300 shadow-sm hover:border-primary transition-colors block"
                >
                  <div className="card-body py-3 px-4 flex-row items-start justify-between gap-3">
                    <div className="flex flex-col gap-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={sev.text}>
                          <AlertTriangle className="h-3.5 w-3.5" />
                        </span>
                        <span className="text-sm font-medium truncate">{item.reason}</span>
                      </div>
                      <p className="text-xs text-base-content/50 truncate">
                        规则 {item.rule_id} · {item.rule_content}
                      </p>
                    </div>
                    <span
                      className={`badge badge-sm shrink-0 ${due.overdue ? "badge-error" : "badge-ghost"}`}
                    >
                      {due.label}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
