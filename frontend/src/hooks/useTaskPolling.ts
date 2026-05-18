import { useEffect, useRef } from "react";
import { getTaskStatus, getTaskResults, getTaskMediaUrl } from "../api/task";
import { POLL_INTERVAL_MS } from "../api/client";
import { useTaskStore } from "../stores/taskStore";
import { useTranscriptStore } from "../stores/transcriptStore";
import { useEvaluationStore } from "../stores/evaluationStore";
import { usePlayerStore } from "../stores/playerStore";
import { useSynthesisStore } from "../stores/synthesisStore";
import type { TranscriptResponse } from "../types/transcript";

export function useTaskPolling(enabled = true) {
  const taskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);
  const updateStatus = useTaskStore((s) => s.updateStatus);
  const setError = useTaskStore((s) => s.setError);
  const setRawEntries = useTranscriptStore((s) => s.setRawEntries);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    if (!enabled || !taskId || status === "completed" || status === "failed") {
      return;
    }

    const poll = async () => {
      try {
        const res = await getTaskStatus(taskId);
        updateStatus(res.status, res.progress);

        if (res.status === "completed" && res.result) {
          // 先加载持久化结果，确保 evaluation 写入 store 后
          // SummaryPanel 的 useEffect 才会看到 existing，不会用默认模板重复提交
          try {
            const results = await getTaskResults(taskId);
            if (results.has_video) {
              usePlayerStore.getState().setMediaSrc(getTaskMediaUrl(taskId), "video");
            }
            if (results.has_synthesis) {
              useSynthesisStore.getState().setHasSynthesis(true);
            }
            if (results.evaluation) {
              const { evaluation: existing } = useEvaluationStore.getState();
              if (!existing) {
                useEvaluationStore.getState().setEvaluation(results.evaluation);
              }
            }
          } catch {
            // 结果读取失败不影响转写展示
          }

          const transcript = res.result as TranscriptResponse;
          if ("transcript" in transcript) {
            setRawEntries(transcript.transcript);
          }

          clearInterval(timerRef.current);
        } else if (res.status === "failed") {
          setError(res.error ?? "任务失败");
          clearInterval(timerRef.current);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "轮询失败");
        clearInterval(timerRef.current);
      }
    };

    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => clearInterval(timerRef.current);
  }, [enabled, taskId, status, updateStatus, setError, setRawEntries]);
}
