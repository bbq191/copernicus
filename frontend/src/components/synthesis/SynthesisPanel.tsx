import { useEffect, useRef, useState } from "react";
import { Mic2, Download, Loader, Play, Pause } from "lucide-react";
import { useTaskStore } from "../../stores/taskStore";
import { useTranscriptStore } from "../../stores/transcriptStore";
import { useSynthesisStore } from "../../stores/synthesisStore";
import {
  startSynthesis,
  getSynthesisStatus,
  getSynthesisAudioUrl,
} from "../../api/synthesis";
import { POLL_INTERVAL_MS } from "../../api/client";
import { useToastStore } from "../../stores/toastStore";
import { formatTime } from "../../utils/formatTime";

export function SynthesisPanel() {
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  // 检查已有合成结果（页面刷新 / 服务重启后恢复）
  useEffect(() => {
    if (!taskId || hasSynthesis) return;
    getSynthesisStatus(taskId)
      .then((s) => {
        if (s.status === "completed") {
          setResult(s.duration_ms ?? 0, s.synthesis_time_ms ?? 0);
        }
      })
      .catch(() => {});
  }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => stopPolling(), []);

  const startPolling = (tid: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await getSynthesisStatus(tid);
        if (s.status === "completed") {
          stopPolling();
          setResult(s.duration_ms ?? 0, s.synthesis_time_ms ?? 0);
          audioRef.current?.load();
          useToastStore.getState().addToast("success", "音频合成完成");
          setLoading(false);
        } else if (s.status === "failed") {
          stopPolling();
          useToastStore
            .getState()
            .addToast("error", s.error ?? "合成失败，请重试");
          setLoading(false);
        }
      } catch {
        // 轮询期间网络抖动 — 继续等待下次
      }
    }, POLL_INTERVAL_MS);
  };

  const handleSynthesize = async () => {
    if (!taskId || loading) return;
    setLoading(true);
    setPlaying(false);
    setCurrentTime(0);
    try {
      await startSynthesis(taskId);
      startPolling(taskId);
    } catch (err) {
      useToastStore
        .getState()
        .addToast("error", err instanceof Error ? err.message : "合成请求失败");
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

  if (rawEntries.length === 0) {
    return (
      <div className="p-4 text-base-content/40 text-center text-sm">
        转录完成后可合成对话音频
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {hasSynthesis && taskId && (
        <>
          <audio
            ref={audioRef}
            src={getSynthesisAudioUrl(taskId)}
            preload="metadata"
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => {
              setPlaying(false);
              setCurrentTime(0);
            }}
            onTimeUpdate={() =>
              setCurrentTime(audioRef.current?.currentTime ?? 0)
            }
            onLoadedMetadata={() =>
              setDuration(audioRef.current?.duration ?? 0)
            }
          />

          <div className="bg-base-200 rounded-xl p-3 flex flex-col gap-2">
            <div className="flex items-center gap-3">
              <button
                className="btn btn-circle btn-sm btn-primary"
                onClick={togglePlay}
              >
                {playing ? (
                  <Pause className="h-4 w-4" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
              </button>

              <div className="flex-1 flex flex-col gap-1">
                <input
                  type="range"
                  min={0}
                  max={duration || 1}
                  step={0.1}
                  value={currentTime}
                  onChange={handleSeek}
                  className="range range-primary range-xs w-full"
                />
                <div className="flex justify-between text-xs text-base-content/50">
                  <span>{formatTime(currentTime)}</span>
                  <span>{formatTime(duration)}</span>
                </div>
              </div>
            </div>

            {(durationMs !== null || synthesisMs !== null) && (
              <div className="text-xs text-base-content/40 flex justify-between px-1">
                {durationMs !== null && (
                  <span>时长 {formatTime(durationMs / 1000)}</span>
                )}
                {synthesisMs !== null && (
                  <span>耗时 {(synthesisMs / 1000).toFixed(1)}s</span>
                )}
              </div>
            )}
          </div>

          <a
            href={getSynthesisAudioUrl(taskId)}
            download={`${taskId}_synthesis.mp3`}
            className="btn btn-sm btn-ghost btn-block gap-1"
          >
            <Download className="h-3.5 w-3.5" />
            下载 MP3
          </a>
        </>
      )}

      <button
        className="btn btn-sm btn-primary btn-block gap-1"
        onClick={handleSynthesize}
        disabled={loading}
      >
        {loading ? (
          <Loader className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Mic2 className="h-3.5 w-3.5" />
        )}
        {loading
          ? "合成中，请稍候..."
          : hasSynthesis
            ? "重新合成"
            : "合成对话音频"}
      </button>

      {!hasSynthesis && (
        <p className="text-xs text-base-content/40 text-center">
          多说话人自动分配音色，LLM 口语化改写
        </p>
      )}
    </div>
  );
}
