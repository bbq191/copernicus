import { useEffect, useRef, useState } from "react";
import { useTaskStore } from "../stores/taskStore";
import { useTranscriptStore } from "../stores/transcriptStore";
import { useSynthesisStore } from "../stores/synthesisStore";
import { startSynthesis, getSynthesisStatus } from "../api/synthesis";
import { createFailureGuard } from "../api/polling";
import { usePolling } from "./usePolling";
import { useToastStore } from "../stores/toastStore";
import { errorMessage } from "../api/errors";

/** 音频重塑的合成状态机（轮询恢复/发起）与播放器控制（播放/暂停/拖动进度）。 */
export function useSynthesisPlayback() {
  const taskId = useTaskStore((s) => s.taskId);
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const hasSynthesis = useSynthesisStore((s) => s.hasSynthesis);
  const durationMs = useSynthesisStore((s) => s.durationMs);
  const synthesisMs = useSynthesisStore((s) => s.synthesisMs);
  const setResult = useSynthesisStore((s) => s.setResult);

  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const audioRef = useRef<HTMLAudioElement>(null);
  const [polling, setPolling] = useState(false);
  // 每次合成完成后递增，附在音频地址上，避免浏览器缓存到上一次的音频
  const [audioVersion, setAudioVersion] = useState(0);
  const guardRef = useRef(createFailureGuard());

  // 进入面板时检查已有结果或进行中的合成（页面刷新 / 服务重启后恢复）
  useEffect(() => {
    if (!taskId || hasSynthesis) return;
    let alive = true;
    getSynthesisStatus(taskId)
      .then((s) => {
        if (!alive) return;
        if (s.status === "completed") {
          setResult(s.duration_ms ?? 0, s.synthesis_time_ms ?? 0);
        } else if (s.status === "running") {
          guardRef.current = createFailureGuard();
          setLoading(true);
          setPolling(true);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  usePolling(
    async (signal) => {
      if (!taskId) return true;
      let s;
      try {
        s = await getSynthesisStatus(taskId);
        guardRef.current.recordSuccess();
      } catch (err) {
        if (signal.aborted) return true;
        if (guardRef.current.shouldRetry(err)) return false; // 网络抖动：下个周期重试
        useToastStore.getState().addToast("error", errorMessage(err, "查询合成状态失败"));
        setPolling(false);
        setLoading(false);
        return true;
      }
      if (signal.aborted) return true;

      if (s.status === "completed") {
        setResult(s.duration_ms ?? 0, s.synthesis_time_ms ?? 0);
        setAudioVersion((v) => v + 1);
        useToastStore.getState().addToast("success", "音频合成完成");
      } else if (s.status === "failed") {
        useToastStore.getState().addToast("error", s.error ?? "合成失败，请重试");
      } else {
        return false;
      }
      setPolling(false);
      setLoading(false);
      return true;
    },
    { enabled: polling },
  );

  const handleSynthesize = async () => {
    if (!taskId || loading) return;
    setLoading(true);
    setPlaying(false);
    setCurrentTime(0);
    try {
      await startSynthesis(taskId);
      guardRef.current = createFailureGuard();
      setPolling(true);
    } catch (err) {
      useToastStore
        .getState()
        .addToast("error", errorMessage(err, "合成请求失败"));
      setLoading(false);
    }
  };

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
    } else {
      if (audio.readyState === 0) audio.load();
      audio.play().catch(() => {});
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;
    const t = Number(e.target.value);
    audio.currentTime = t;
    setCurrentTime(t);
  };

  return {
    taskId,
    rawEntries,
    hasSynthesis,
    durationMs,
    synthesisMs,
    loading,
    playing,
    currentTime,
    duration,
    audioRef,
    audioVersion,
    handleSynthesize,
    togglePlay,
    handleSeek,
    setPlaying,
    setCurrentTime,
    setDuration,
  };
}
