import { useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2, ListChecks } from "lucide-react";
import { useRuleLibrary } from "../hooks/useRuleLibrary";
import { ThemeToggle } from "../components/shared/ThemeToggle";
import { RuleFormModal } from "../components/rules/RuleFormModal";
import { CATEGORY_LABEL, CHECK_MODE_LABEL, EVIDENCE_LABEL, SEVERITY_BADGE, SEVERITY_LABEL } from "../components/rules/ruleLabels";

export function RuleLibraryPage() {
  const navigate = useNavigate();
  const {
    rules,
    loading,
    error,
    editing,
    setEditing,
    confirmDeleteId,
    setConfirmDeleteId,
    toggleEnabled,
    handleDelete,
    handleRuleSaved,
  } = useRuleLibrary();

  return (
    <div className="min-h-screen flex flex-col">
      <div className="navbar bg-base-100 border-b border-base-300 px-4 min-h-12">
        <div className="flex-1">
          <button className="btn btn-ghost text-xl" onClick={() => navigate("/")}>
            Copernicus
          </button>
          <span className="text-base-content/40 ml-1">/ 合规规则库</span>
        </div>
        <div className="flex-none gap-2">
          <ThemeToggle />
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 max-w-4xl mx-auto w-full">
        <div className="flex items-center justify-between gap-2 flex-wrap mb-4">
          <div className="flex items-center gap-2 flex-wrap">
            <ListChecks className="h-5 w-5" />
            <h1 className="text-xl font-semibold">合规规则库</h1>
            <span className="hidden sm:inline text-xs text-base-content/40">
              跨任务复用的自定义规则，提交合规审核时可整体选用
            </span>
          </div>
          <button className="btn btn-primary btn-sm gap-1" onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" />
            新增规则
          </button>
        </div>

        {error && (
          <div className="alert alert-error mb-4">
            <span className="text-sm">{error}</span>
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <span className="loading loading-spinner" />
          </div>
        ) : rules.length === 0 ? (
          <p className="text-sm text-base-content/40 text-center py-12">
            规则库为空，点击右上角新增一条规则
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead>
                <tr>
                  <th>标题</th>
                  <th>分类</th>
                  <th>检查方式</th>
                  <th>证据来源</th>
                  <th>严重度</th>
                  <th>状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id}>
                    <td className="max-w-xs truncate" title={rule.content}>
                      {rule.title}
                    </td>
                    <td>{CATEGORY_LABEL[rule.category]}</td>
                    <td>{CHECK_MODE_LABEL[rule.check_mode]}</td>
                    <td>{rule.evidence_sources.map((s) => EVIDENCE_LABEL[s]).join("、")}</td>
                    <td>
                      <span className={`badge badge-sm ${SEVERITY_BADGE[rule.severity_default]}`}>
                        {SEVERITY_LABEL[rule.severity_default]}
                      </span>
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        className="toggle toggle-sm toggle-success"
                        checked={rule.enabled}
                        onChange={() => void toggleEnabled(rule)}
                        aria-label={rule.enabled ? "已启用" : "已停用"}
                      />
                    </td>
                    <td>
                      {confirmDeleteId === rule.id ? (
                        <div className="flex items-center gap-1 text-xs whitespace-nowrap">
                          <span className="text-error">确认删除？</span>
                          <button className="btn btn-xs btn-error" onClick={() => void handleDelete(rule.id)}>
                            删除
                          </button>
                          <button className="btn btn-xs btn-ghost" onClick={() => setConfirmDeleteId(null)}>
                            取消
                          </button>
                        </div>
                      ) : (
                        <div className="flex gap-1 justify-end">
                          <button
                            className="btn btn-xs btn-ghost"
                            aria-label="编辑"
                            onClick={() => setEditing(rule)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            className="btn btn-xs btn-ghost text-error"
                            aria-label="删除"
                            onClick={() => setConfirmDeleteId(rule.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && (
        <RuleFormModal
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={handleRuleSaved}
        />
      )}
    </div>
  );
}
