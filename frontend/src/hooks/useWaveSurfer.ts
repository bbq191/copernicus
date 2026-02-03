import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import { usePlayerStore } from "../stores/playerStore";

export function useWaveSurfer(
  containerRef: React.RefObject<HTMLDivElement | null>,
  audioRef: React.RefObject<HTMLAudioElement | null>,
) {
  const wsRef = useRef<WaveSurfer | null>(null);
  const audioSrc = usePlayerStore((s) => s.audioSrc);

  useEffect(() => {
    if (!containerRef.current || !audioRef.current || !audioSrc) return;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      media: audioRef.current,
      height: 80,
      waveColor: "#4F46E5",
      progressColor: "#818CF8",
      cursorColor: "#312E81",
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
    });

    wsRef.current = ws;

    return () => {
      ws.destroy();
      wsRef.current = null;
    };
  }, [containerRef, audioRef, audioSrc]);

  return wsRef;
}
