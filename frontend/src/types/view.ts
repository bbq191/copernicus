import type { TranscriptEntry } from "./transcript";

export interface MergedBlock {
  id: string;
  speaker: string;
  startMs: number;
  endMs: number;
  sentences: TranscriptEntry[];
}
