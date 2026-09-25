import { create } from "zustand";
import type { TranscriptEntry, TranscriptResponse } from "../types/transcript";
import type { MergedBlock } from "../types/view";
import { processTranscriptForView } from "../utils/processTranscript";

type TextMode = "original" | "corrected";

/** 按首次出现顺序返回去重后的说话人列表。 */
function uniqueSpeakers(entries: TranscriptEntry[]): string[] {
  return [...new Set(entries.map((e) => e.speaker))];
}

function deriveView(entries: TranscriptEntry[]) {
  return {
    rawEntries: entries,
    mergedBlocks: processTranscriptForView(entries),
    speakers: uniqueSpeakers(entries),
  };
}

interface TranscriptState {
  /** 转写条目：与后端持久化内容保持一致（人工校对成功后同步更新） */
  rawEntries: TranscriptEntry[];
  mergedBlocks: MergedBlock[];
  /** 说话人列表（按首次出现顺序） */
  speakers: string[];
  textMode: TextMode;
  searchQuery: string;
  visibleSpeakers: Set<string>;
  /** LLM 润色的批次统计，用于提示"部分文本未经润色" */
  correction: CorrectionStats;

  setRawEntries: (entries: TranscriptEntry[]) => void;
  /** 载入服务端返回的完整转写（条目 + 润色统计） */
  setTranscript: (response: TranscriptResponse) => void;
  /** 本地更新某句的修正文（调用方负责与后端同步/回滚） */
  setSentenceText: (index: number, text: string) => void;
  /** 本地应用说话人重命名/合并，{原名: 新名} */
  applySpeakerRenames: (renames: Record<string, string>) => void;
  setTextMode: (mode: TextMode) => void;
  setSearchQuery: (q: string) => void;
  toggleSpeakerVisibility: (speaker: string) => void;
}

export interface CorrectionStats {
  total: number;
  failed: number;
}

const NO_CORRECTION: CorrectionStats = { total: 0, failed: 0 };

export const useTranscriptStore = create<TranscriptState>((set) => ({
  correction: NO_CORRECTION,
  rawEntries: [],
  mergedBlocks: [],
  speakers: [],
  textMode: "corrected",
  searchQuery: "",
  visibleSpeakers: new Set<string>(),

  setRawEntries: (entries) =>
    set({
      ...deriveView(entries),
      visibleSpeakers: new Set(uniqueSpeakers(entries)),
      // 清空（切换/重置工作区）时同时清掉统计；校对编辑不走这里
      ...(entries.length === 0 ? { correction: NO_CORRECTION } : {}),
    }),

  setTranscript: (response) =>
    set({
      ...deriveView(response.transcript),
      visibleSpeakers: new Set(uniqueSpeakers(response.transcript)),
      correction: {
        total: response.correction_total_batches ?? 0,
        failed: response.correction_failed_batches ?? 0,
      },
    }),

  setSentenceText: (index, text) =>
    set((state) =>
      deriveView(
        state.rawEntries.map((e, i) =>
          i === index ? { ...e, text_corrected: text } : e,
        ),
      ),
    ),

  applySpeakerRenames: (renames) =>
    set((state) => {
      const rename = (name: string) => renames[name] ?? name;
      // 合并后的说话人：只要有一个来源可见即可见
      const visible = new Set([...state.visibleSpeakers].map(rename));
      return {
        ...deriveView(state.rawEntries.map((e) => ({ ...e, speaker: rename(e.speaker) }))),
        visibleSpeakers: visible,
      };
    }),

  setTextMode: (mode) => set({ textMode: mode }),

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
