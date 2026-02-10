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
  const mediaSrc = usePlayerStore((s) => s.mediaSrc);

  useAudioSync(audioRef);
  useWaveSurfer(waveformRef, audioRef);

  if (!mediaSrc) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <audio ref={audioRef} src={mediaSrc} preload="metadata" />
      <WaveformDisplay containerRef={waveformRef} />
      <ProgressBar />
      <PlaybackControls />
    </div>
  );
}
