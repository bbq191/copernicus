import { describe, expect, it } from "vitest";
import { processTranscriptForView } from "./processTranscript";
import type { TranscriptEntry } from "../types/transcript";

const entry = (speaker: string, startMs: number, endMs: number): TranscriptEntry => ({
  timestamp: "",
  timestamp_ms: startMs,
  end_ms: endMs,
  speaker,
  text: `原文${startMs}`,
  text_corrected: `修正${startMs}`,
});

describe("processTranscriptForView", () => {
  it("merges consecutive sentences of the same speaker within 30s", () => {
    const blocks = processTranscriptForView([
      entry("A", 0, 1000),
      entry("A", 5000, 6000),
      entry("A", 20_000, 21_000),
    ]);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].sentences).toHaveLength(3);
    expect(blocks[0].endMs).toBe(21_000);
  });

  it("starts a new block when the speaker changes", () => {
    const blocks = processTranscriptForView([entry("A", 0, 1000), entry("B", 1000, 2000), entry("A", 2000, 3000)]);
    expect(blocks.map((b) => b.speaker)).toEqual(["A", "B", "A"]);
    expect(blocks.map((b) => b.id)).toEqual(["block-0", "block-1", "block-2"]);
  });

  it("starts a new block when the gap reaches 30s", () => {
    const blocks = processTranscriptForView([entry("A", 0, 1000), entry("A", 31_000, 32_000)]);
    expect(blocks).toHaveLength(2);
  });

  it("returns an empty list for empty input", () => {
    expect(processTranscriptForView([])).toEqual([]);
  });

  it("keeps entry object identity so edits can locate the entry", () => {
    const first = entry("A", 0, 1000);
    const [block] = processTranscriptForView([first]);
    expect(block.sentences[0]).toBe(first);
  });
});
