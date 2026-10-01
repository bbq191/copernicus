import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2, ListChecks } from "lucide-react";
import { createRule, deleteRule, listRules, updateRule } from "../api/rules";
import { errorMessage } from "../api/errors";
import { useToastStore } from "../stores/toastStore";
import { ThemeToggle } from "../components/shared/ThemeToggle";
import type { CheckMode, CustomRule, CustomRuleInput, EvidenceSource, RuleCategory, RuleSeverity } from "../types/rules";

const CATEGORY_LABEL: Record<RuleCategory, string> = {
  forbidden_phrase: "禁止用语",
  behavioral: "行为规范",
  document: "文件/资料要求",
  visual_check: "视觉检查",
};

const CHECK_MODE_LABEL: Record<CheckMode, string> = {
  exact: "精确关键词匹配",
  semantic: "语义审核（LLM）",
  visual: "视觉审核（需 OCR）",
};

const EVIDENCE_LABEL: Record<EvidenceSource, string> = {
  transcript: "转写文本",
  ocr: "画面文字",
  vision: "人脸检测",
};

const SEVERITY_LABEL: Record<RuleSeverity, string> = { high: "高", medium: "中", low: "低" };
const SEVERITY_BADGE: Record<RuleSeverity, string> = {
  high: "badge-error", medium: "badge-warning", low: "badge-info",
};

const EMPTY_DRAFT: CustomRuleInput = {
  title: "", content: "", category: "behavioral", check_mode: "semantic",
  evidence_sources: ["transcript"], keywords: [], description: "", severity_default: "medium",
  enabled: true,
};

export function RuleLibraryPage() {
  const navigate = useNavigate();
  const [rules, setRules] = useState<CustomRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<CustomRule | "new" | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setRules(await listRules());
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "加载规则库失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const toggleEnabled = async (rule: CustomRule) => {
    try {
      const updated = await updateRule(rule.id, { enabled: !rule.enabled });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch (err) {
      useToastStore.getState().addToast("error", errorMessage(err, "更新失败"));
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteRule(id);
      setRules((prev) => prev.filter((r) => r.id !== id));
      useToastStore.getState().addToast("success", "已删除");
    } catch (err) {
      useToastStore.getState().addToast("error", errorMessage(err, "删除失败"));
    } finally {
      setConfirmDeleteId(null);
    }
  };

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

      <div className="flex-1 p-6 max-w-4xl mx-auto w-full">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <ListChecks className="h-5 w-5" />
            <h1 className="text-xl font-semibold">合规规则库</h1>
            <span className="text-xs text-base-content/40">
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
          onSaved={(rule) => {
            setRules((prev) =>
              editing === "new" ? [...prev, rule] : prev.map((r) => (r.id === rule.id ? rule : r)),
            );
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

function RuleFormModal({
  initial,
  onClose,
  onSaved,
}: {
  initial: CustomRule | null;
  onClose: () => void;
  onSaved: (rule: CustomRule) => void;
}) {
  const [draft, setDraft] = useState<CustomRuleInput>(initial ?? EMPTY_DRAFT);
  const [keywordsText, setKeywordsText] = useState((initial?.keywords ?? []).join("、"));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleEvidence = (source: EvidenceSource) => {
    setDraft((d) => ({
      ...d,
      evidence_sources: d.evidence_sources.includes(source)
        ? d.evidence_sources.filter((s) => s !== source)
        : [...d.evidence_sources, source],
    }));
  };

  const handleSave = async () => {
    if (!draft.title.trim() || !draft.content.trim()) {
      setError("标题和规则内容不能为空");
      return;
    }
    if (draft.evidence_sources.length === 0) {
      setError("至少选择一个证据来源");
      return;
    }
    setSaving(true);
    setError(null);
    const payload: CustomRuleInput = {
      ...draft,
      keywords: keywordsText.split(/[,，、]/).map((k) => k.trim()).filter(Boolean),
    };
    try {
      const saved = initial ? await updateRule(initial.id, payload) : await createRule(payload);
      onSaved(saved);
    } catch (err) {
      setError(errorMessage(err, "保存失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <dialog className="modal modal-open">
      <div className="modal-box max-w-lg">
        <h3 className="font-bold text-lg mb-4">{initial ? "编辑规则" : "新增规则"}</h3>

        <div className="flex flex-col gap-3">
          <label className="form-control">
            <span className="label-text text-xs mb-1">标题</span>
            <input
              className="input input-bordered input-sm"
              maxLength={100}
              value={draft.title}
              onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
            />
          </label>

          <label className="form-control">
            <span className="label-text text-xs mb-1">规则内容（注入审核 prompt）</span>
            <textarea
              className="textarea textarea-bordered textarea-sm"
              rows={2}
              maxLength={2000}
              value={draft.content}
              onChange={(e) => setDraft((d) => ({ ...d, content: e.target.value }))}
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="form-control">
              <span className="label-text text-xs mb-1">分类</span>
              <select
                className="select select-bordered select-sm"
                value={draft.category}
                onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value as RuleCategory }))}
              >
                {Object.entries(CATEGORY_LABEL).map(([v, label]) => (
                  <option key={v} value={v}>{label}</option>
                ))}
              </select>
            </label>
            <label className="form-control">
              <span className="label-text text-xs mb-1">检查方式</span>
              <select
                className="select select-bordered select-sm"
                value={draft.check_mode}
                onChange={(e) => setDraft((d) => ({ ...d, check_mode: e.target.value as CheckMode }))}
              >
                {Object.entries(CHECK_MODE_LABEL).map(([v, label]) => (
                  <option key={v} value={v}>{label}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="form-control">
            <span className="label-text text-xs mb-1">证据来源</span>
            <div className="flex gap-4">
              {(Object.keys(EVIDENCE_LABEL) as EvidenceSource[]).map((source) => (
                <label key={source} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    className="checkbox checkbox-xs"
                    checked={draft.evidence_sources.includes(source)}
                    onChange={() => toggleEvidence(source)}
                  />
                  {EVIDENCE_LABEL[source]}
                </label>
              ))}
            </div>
          </div>

          {draft.check_mode === "exact" && (
            <label className="form-control">
              <span className="label-text text-xs mb-1">关键词（顿号或逗号分隔；仅精确匹配使用）</span>
              <input
                className="input input-bordered input-sm"
                value={keywordsText}
                onChange={(e) => setKeywordsText(e.target.value)}
                placeholder="保本、保息"
              />
              <span className="label-text-alt text-xs text-base-content/40 mt-1">
                自定义规则的精确匹配仅由 LLM 判断，不会像内置规则一样做正则与拼音二次校验
              </span>
            </label>
          )}

          <label className="form-control">
            <span className="label-text text-xs mb-1">审核说明（供 LLM 判断依据，可选）</span>
            <textarea
              className="textarea textarea-bordered textarea-sm"
              rows={2}
              maxLength={2000}
              value={draft.description}
              onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            />
          </label>

          <div className="grid grid-cols-2 gap-3 items-end">
            <label className="form-control">
              <span className="label-text text-xs mb-1">默认严重度</span>
              <select
                className="select select-bordered select-sm"
                value={draft.severity_default}
                onChange={(e) => setDraft((d) => ({ ...d, severity_default: e.target.value as RuleSeverity }))}
              >
                {Object.entries(SEVERITY_LABEL).map(([v, label]) => (
                  <option key={v} value={v}>{label}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm pb-2">
              <input
                type="checkbox"
                className="toggle toggle-sm toggle-success"
                checked={draft.enabled}
                onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
              />
              启用
            </label>
          </div>

          {error && <p className="text-sm text-error">{error}</p>}
        </div>

        <div className="modal-action">
          <button className="btn btn-ghost" onClick={onClose} disabled={saving}>
            取消
          </button>
          <button className="btn btn-primary" onClick={() => void handleSave()} disabled={saving}>
            {saving && <span className="loading loading-spinner loading-xs" />}
            保存
          </button>
        </div>
      </div>
      <form method="dialog" className="modal-backdrop">
        <button onClick={onClose}>close</button>
      </form>
    </dialog>
  );
}
