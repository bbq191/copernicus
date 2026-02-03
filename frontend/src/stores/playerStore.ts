import { create } from "zustand";

interface PlayerState {
  audioSrc: string | null;
  audioElement: HTMLAudioElement | null;
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  playbackRate: number;
  volume: number;

  setAudioSrc: (src: string) => void;
  setAudioElement: (el: HTMLAudioElement | null) => void;
  setCurrentTime: (ms: number) => void;
  setDuration: (ms: number) => void;
  seekTo: (ms: number) => void;
  togglePlay: () => void;
  setPlaying: (playing: boolean) => void;
  setPlaybackRate: (rate: number) => void;
  setVolume: (vol: number) => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  audioSrc: null,
  audioElement: null,
  currentTime: 0,
  duration: 0,
  isPlaying: false,
  playbackRate: 1,
  volume: 1,

  setAudioSrc: (src) => set({ audioSrc: src }),
  setAudioElement: (el) => set({ audioElement: el }),
  setCurrentTime: (ms) => set({ currentTime: ms }),
  setDuration: (ms) => set({ duration: ms }),

  seekTo: (ms) => {
    const el = get().audioElement;
    if (el) el.currentTime = ms / 1000;
    set({ currentTime: ms });
  },

  togglePlay: () => {
    const { audioElement, isPlaying } = get();
    if (!audioElement) return;
    if (isPlaying) {
      audioElement.pause();
    } else {
      audioElement.play();
    }
    set({ isPlaying: !isPlaying });
  },

  setPlaying: (playing) => set({ isPlaying: playing }),

  setPlaybackRate: (rate) => {
    const el = get().audioElement;
    if (el) el.playbackRate = rate;
    set({ playbackRate: rate });
  },

  setVolume: (vol) => {
    const el = get().audioElement;
    if (el) el.volume = vol;
    set({ volume: vol });
  },
}));
