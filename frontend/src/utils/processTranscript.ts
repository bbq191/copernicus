import type { TranscriptEntry } from "../types/transcript";
import type { MergedBlock } from "../types/view";

const MERGE_GAP_MS = 30_000;

export function processTranscriptForView(
  rawList: TranscriptEntry[],
): MergedBlock[] {
  const blocks: MergedBlock[] = [];
  let current: MergedBlock | null = null;

  for (const item of rawList) {
    if (
      current &&
      current.speaker === item.speaker &&
      item.timestamp_ms - current.endMs < MERGE_GAP_MS
    ) {
      current.sentences.push(item);
      current.endMs = item.timestamp_ms;
    } else {
      if (current) blocks.push(current);
      current = {
        id: `block-${blocks.length}`,
        speaker: item.speaker,
        startMs: item.timestamp_ms,
        endMs: item.timestamp_ms,
        sentences: [item],
      };
    }
  }
  if (current) blocks.push(current);
  return blocks;
}
