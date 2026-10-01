import { useCallback, useEffect, useState } from "react";
import { deleteRule, listRules, updateRule } from "../api/rules";
import { errorMessage } from "../api/errors";
import { useToastStore } from "../stores/toastStore";
import type { CustomRule } from "../types/rules";

/** 合规规则库的列表加载、启用切换、删除与编辑弹窗状态。 */
export function useRuleLibrary() {
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

  const toggleEnabled = useCallback(async (rule: CustomRule) => {
    try {
      const updated = await updateRule(rule.id, { enabled: !rule.enabled });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch (err) {
      useToastStore.getState().addToast("error", errorMessage(err, "更新失败"));
    }
  }, []);

  const handleDelete = useCallback(async (id: number) => {
    try {
      await deleteRule(id);
      setRules((prev) => prev.filter((r) => r.id !== id));
      useToastStore.getState().addToast("success", "已删除");
    } catch (err) {
      useToastStore.getState().addToast("error", errorMessage(err, "删除失败"));
    } finally {
      setConfirmDeleteId(null);
    }
  }, []);

  const handleRuleSaved = useCallback(
    (rule: CustomRule) => {
      setRules((prev) =>
        editing === "new" ? [...prev, rule] : prev.map((r) => (r.id === rule.id ? rule : r)),
      );
      setEditing(null);
    },
    [editing],
  );

  return {
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
  };
}
