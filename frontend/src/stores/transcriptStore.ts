import { create } from "zustand";
import type { TranscriptEntry } from "../types/transcript";
import type { MergedBlock } from "../types/view";
import { processTranscriptForView } from "../utils/processTranscript";

type TextMode = "original" | "corrected";

interface TranscriptState {
  rawEntries: TranscriptEntry[];
  mergedBlocks: MergedBlock[];
  speakerMap: Record<string, string>;
  textMode: TextMode;
  editedTexts: Record<string, string>;
  searchQuery: string;
  visibleSpeakers: Set<string>;

  setRawEntries: (entries: TranscriptEntry[]) => void;
  renameSpeaker: (oldName: string, newName: string) => void;
  setTextMode: (mode: TextMode) => void;
  updateText: (key: string, text: string) => void;
  setSearchQuery: (q: string) => void;
  toggleSpeakerVisibility: (speaker: string) => void;
}

export const useTranscriptStore = create<TranscriptState>((set) => ({
  rawEntries: [],
  mergedBlocks: [],
  speakerMap: {},
  textMode: "corrected",
  editedTexts: {},
  searchQuery: "",
  visibleSpeakers: new Set<string>(),

  setRawEntries: (entries) => {
    const blocks = processTranscriptForView(entries);
    const speakers: Record<string, string> = {};
    const allSpeakers = new Set<string>();
    for (const e of entries) {
      if (!speakers[e.speaker]) speakers[e.speaker] = e.speaker;
      allSpeakers.add(e.speaker);
    }
    set({ rawEntries: entries, mergedBlocks: blocks, speakerMap: speakers, visibleSpeakers: allSpeakers });
  },

  renameSpeaker: (oldName, newName) =>
    set((state) => ({
      speakerMap: { ...state.speakerMap, [oldName]: newName },
    })),

  setTextMode: (mode) => set({ textMode: mode }),

  updateText: (key, text) =>
    set((state) => ({
      editedTexts: { ...state.editedTexts, [key]: text },
    })),

  setSearchQuery: (q) => set({ searchQuery: q }),

  toggleSpeakerVisibility: (speaker) =>
    set((state) => {
      const next = new Set(state.visibleSpeakers);
      if (next.has(speaker)) {
        next.delete(speaker);
      } else {
        next.add(speaker);
      }
      return { visibleSpeakers: next };
    }),
}));
