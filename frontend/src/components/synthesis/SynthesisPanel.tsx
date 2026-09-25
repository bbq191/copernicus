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
import { createFailureGuard } from "../../api/polling";
import { usePolling } from "../../hooks/usePolling";
import { useToastStore } from "../../stores/toastStore";
import { formatTime } from "../../utils/formatTime";
import { errorMessage } from "../../api/errors";

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
            src={`${getSynthesisAudioUrl(taskId)}?v=${audioVersion}`}
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
                  <span>{formatTime(currentTime * 1000)}</span>
                  <span>{formatTime(duration * 1000)}</span>
                </div>
              </div>
            </div>

            {(durationMs !== null || synthesisMs !== null) && (
              <div className="text-xs text-base-content/40 flex justify-between px-1">
                {durationMs !== null && (
                  <span>时长 {formatTime(durationMs)}</span>
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
