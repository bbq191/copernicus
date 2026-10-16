import { useCallback, useEffect, useRef, useState } from "react";
import { countAffectedTasks, getReauditJob, startReaudit } from "../api/rules";
import { errorMessage } from "../api/errors";
import { useToastStore } from "../stores/toastStore";
import type { ReauditJobStatus } from "../types/rules";

const POLL_INTERVAL_MS = 2000;

/** 规则编辑保存后，提示"是否重新审核受影响的历史任务"，并跟踪批量重审的进度。 */
export function useRuleReaudit() {
  const [prompt, setPrompt] = useState<{ ruleId: number; total: number } | null>(null);
  const [job, setJob] = useState<ReauditJobStatus | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => () => clearInterval(timerRef.current), []);

  const startPolling = useCallback((jobId: string) => {
    clearInterval(timerRef.current);
    let inFlight = false;
    timerRef.current = setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      getReauditJob(jobId)
        .then((status) => {
          setJob(status);
          if (status.done) clearInterval(timerRef.current);
        })
        .catch((err) => {
          clearInterval(timerRef.current);
          useToastStore.getState().addToast("error", errorMessage(err, "查询重审进度失败"));
        })
        .finally(() => {
          inFlight = false;
        });
    }, POLL_INTERVAL_MS);
  }, []);

  /** 规则保存后调用：有历史任务引用这条规则时才弹出提示。 */
  const checkAfterEdit = useCallback(async (ruleId: number) => {
    try {
      const { total } = await countAffectedTasks(ruleId);
      if (total > 0) setPrompt({ ruleId, total });
    } catch {
      // 查询失败就不打扰用户：少一次提示，不影响规则本身已经保存成功
    }
  }, []);

  const confirmReaudit = useCallback(() => {
    if (!prompt) return;
    const { ruleId } = prompt;
    setPrompt(null);
    startReaudit(ruleId)
      .then(({ job_id, total }) => {
        setJob({ id: job_id, rule_id: ruleId, total, completed: 0, failed: [], done: false, diffs: [] });
        startPolling(job_id);
      })
      .catch((err) => {
        useToastStore.getState().addToast("error", errorMessage(err, "发起重审失败"));
      });
  }, [prompt, startPolling]);

  const dismissPrompt = useCallback(() => setPrompt(null), []);
  const dismissJob = useCallback(() => {
    clearInterval(timerRef.current);
    setJob(null);
  }, []);

  return { prompt, job, checkAfterEdit, confirmReaudit, dismissPrompt, dismissJob };
}
