import { useRef } from "react";
import { usePlayerStore } from "../../stores/playerStore";
import { useAudioSync } from "../../hooks/useAudioSync";
import { useWaveSurfer } from "../../hooks/useWaveSurfer";
import { PlaybackControls } from "./PlaybackControls";
import { ProgressBar } from "./ProgressBar";
import { WaveformDisplay } from "./WaveformDisplay";

export function AudioPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const waveformRef = useRef<HTMLDivElement>(null);
  const audioSrc = usePlayerStore((s) => s.audioSrc);

  useAudioSync(audioRef);
  useWaveSurfer(waveformRef, audioRef);

  if (!audioSrc) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <audio ref={audioRef} src={audioSrc} preload="metadata" />
      <WaveformDisplay containerRef={waveformRef} />
      <ProgressBar />
      <PlaybackControls />
    </div>
  );
}
