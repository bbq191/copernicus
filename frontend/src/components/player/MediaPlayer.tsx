import { useRef } from "react";
import { usePlayerStore } from "../../stores/playerStore";
import { useAudioSync } from "../../hooks/useAudioSync";
import { useWaveSurfer } from "../../hooks/useWaveSurfer";
import { PlaybackControls } from "./PlaybackControls";
import { ProgressBar } from "./ProgressBar";
import { WaveformDisplay } from "./WaveformDisplay";

export function MediaPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const waveformRef = useRef<HTMLDivElement>(null);
  const mediaSrc = usePlayerStore((s) => s.mediaSrc);
  const mediaType = usePlayerStore((s) => s.mediaType);

  const isVideo = mediaType === "video";
  const activeRef = isVideo ? videoRef : audioRef;

  useAudioSync(activeRef);
  useWaveSurfer(waveformRef, isVideo ? { current: null } : audioRef);

  if (!mediaSrc) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      {isVideo ? (
        <video
          ref={videoRef}
          src={mediaSrc}
          preload="metadata"
          className="w-full rounded-lg bg-black aspect-video"
        />
      ) : (
        <>
          <audio ref={audioRef} src={mediaSrc} preload="metadata" />
          <WaveformDisplay containerRef={waveformRef} />
        </>
      )}
      <ProgressBar />
      <PlaybackControls />
    </div>
  );
}
