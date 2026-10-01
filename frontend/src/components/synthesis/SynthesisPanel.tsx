import { Mic2, Download, Loader, Play, Pause } from "lucide-react";
import { useSynthesisPlayback } from "../../hooks/useSynthesisPlayback";
import { getSynthesisAudioUrl } from "../../api/synthesis";
import { formatTime } from "../../utils/formatTime";

export function SynthesisPanel() {
  const {
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
  } = useSynthesisPlayback();

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
