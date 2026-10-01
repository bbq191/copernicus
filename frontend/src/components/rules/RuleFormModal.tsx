import { useState } from "react";
import { createRule, updateRule } from "../../api/rules";
import { errorMessage } from "../../api/errors";
import {
  RULE_CONTENT_MAX_LEN,
  RULE_DESCRIPTION_MAX_LEN,
  RULE_TITLE_MAX_LEN,
  type CheckMode,
  type CustomRule,
  type CustomRuleInput,
  type EvidenceSource,
  type RuleCategory,
  type RuleSeverity,
} from "../../types/rules";
import { CATEGORY_LABEL, CHECK_MODE_LABEL, EMPTY_RULE_DRAFT, EVIDENCE_LABEL, SEVERITY_LABEL } from "./ruleLabels";

interface Props {
  initial: CustomRule | null;
  onClose: () => void;
  onSaved: (rule: CustomRule) => void;
}

export function RuleFormModal({ initial, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<CustomRuleInput>(initial ?? EMPTY_RULE_DRAFT);
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
              maxLength={RULE_TITLE_MAX_LEN}
              value={draft.title}
              onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
            />
          </label>

          <label className="form-control">
            <span className="label-text text-xs mb-1">规则内容（注入审核 prompt）</span>
            <textarea
              className="textarea textarea-bordered textarea-sm"
              rows={2}
              maxLength={RULE_CONTENT_MAX_LEN}
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
              maxLength={RULE_DESCRIPTION_MAX_LEN}
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
