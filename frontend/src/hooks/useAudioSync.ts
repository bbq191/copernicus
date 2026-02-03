import { useEffect, useRef } from "react";
import { usePlayerStore } from "../stores/playerStore";

export function useAudioSync(audioRef: React.RefObject<HTMLAudioElement | null>) {
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);
  const setCurrentTime = usePlayerStore((s) => s.setCurrentTime);
  const setDuration = usePlayerStore((s) => s.setDuration);
  const setPlaying = usePlayerStore((s) => s.setPlaying);
  const setAudioElement = usePlayerStore((s) => s.setAudioElement);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;

    setAudioElement(el);

    const onLoadedMetadata = () => {
      setDuration(el.duration * 1000);
    };

    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => setPlaying(false);

    el.addEventListener("loadedmetadata", onLoadedMetadata);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onEnded);

    const tick = () => {
      const nowMs = el.currentTime * 1000;
      if (Math.abs(nowMs - lastTimeRef.current) >= 50) {
        lastTimeRef.current = nowMs;
        setCurrentTime(nowMs);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      el.removeEventListener("loadedmetadata", onLoadedMetadata);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onEnded);
      setAudioElement(null);
    };
  }, [audioRef, setCurrentTime, setDuration, setPlaying, setAudioElement]);
}
