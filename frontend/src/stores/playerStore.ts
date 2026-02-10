import { create } from "zustand";

interface LoopRegion {
  startMs: number;
  endMs: number;
}

type MediaType = "video" | "audio";

interface PlayerState {
  mediaSrc: string | null;
  mediaElement: HTMLMediaElement | null;
  mediaType: MediaType;
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  playbackRate: number;
  volume: number;
  loopEnabled: boolean;
  loopRegion: LoopRegion | null;

  setMediaSrc: (src: string, type?: MediaType) => void;
  setMediaElement: (el: HTMLMediaElement | null) => void;
  setCurrentTime: (ms: number) => void;
  setDuration: (ms: number) => void;
  seekTo: (ms: number) => void;
  seekAndPlay: (ms: number) => void;
  togglePlay: () => void;
  setPlaying: (playing: boolean) => void;
  setPlaybackRate: (rate: number) => void;
  setVolume: (vol: number) => void;
  setLoopEnabled: (enabled: boolean) => void;
  setLoopRegion: (region: LoopRegion | null) => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  mediaSrc: null,
  mediaElement: null,
  mediaType: "audio",
  currentTime: 0,
  duration: 0,
  isPlaying: false,
  playbackRate: 1,
  volume: 1,
  loopEnabled: false,
  loopRegion: null,

  setMediaSrc: (src, type = "audio") => set({ mediaSrc: src, mediaType: type }),
  setMediaElement: (el) => set({ mediaElement: el }),
  setCurrentTime: (ms) => set({ currentTime: ms }),
  setDuration: (ms) => set({ duration: ms }),

  seekTo: (ms) => {
    const el = get().mediaElement;
    if (el) el.currentTime = ms / 1000;
    set({ currentTime: ms });
  },

  seekAndPlay: (ms) => {
    const el = get().mediaElement;
    if (!el) return;
    el.currentTime = ms / 1000;
    set({ currentTime: ms });
    el.play().then(
      () => set({ isPlaying: true }),
      () => set({ isPlaying: false }),
    );
  },

  togglePlay: () => {
    const { mediaElement, isPlaying } = get();
    if (!mediaElement) return;
    if (isPlaying) {
      mediaElement.pause();
    } else {
      mediaElement.play();
    }
    set({ isPlaying: !isPlaying });
  },

  setPlaying: (playing) => set({ isPlaying: playing }),

  setPlaybackRate: (rate) => {
    const el = get().mediaElement;
    if (el) el.playbackRate = rate;
    set({ playbackRate: rate });
  },

  setVolume: (vol) => {
    const el = get().mediaElement;
    if (el) el.volume = vol;
    set({ volume: vol });
  },

  setLoopEnabled: (enabled) => set({ loopEnabled: enabled }),
  setLoopRegion: (region) => set({ loopRegion: region }),
}));
