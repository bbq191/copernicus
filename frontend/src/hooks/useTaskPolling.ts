import { useEffect, useRef } from "react";
import { getTaskStatus } from "../api/task";
import { useTaskStore } from "../stores/taskStore";
import { useTranscriptStore } from "../stores/transcriptStore";
import type { TranscriptResponse } from "../types/transcript";

const POLL_INTERVAL = 2000;

export function useTaskPolling() {
  const taskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);
  const updateStatus = useTaskStore((s) => s.updateStatus);
  const setError = useTaskStore((s) => s.setError);
  const setRawEntries = useTranscriptStore((s) => s.setRawEntries);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    if (!taskId || status === "completed" || status === "failed") {
      return;
    }

    const poll = async () => {
      try {
        const res = await getTaskStatus(taskId);
        updateStatus(res.status, res.progress);

        if (res.status === "completed" && res.result) {
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
    timerRef.current = setInterval(poll, POLL_INTERVAL);

    return () => clearInterval(timerRef.current);
  }, [taskId, status, updateStatus, setError, setRawEntries]);
}
