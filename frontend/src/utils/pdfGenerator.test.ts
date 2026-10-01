import { describe, expect, it } from "vitest";
import { buildPdfLines } from "./pdfGenerator";
import type { MergedBlock } from "../types/view";
import type { TranscriptEntry } from "../types/transcript";

const entry = (text: string, corrected: string): TranscriptEntry => ({
  timestamp: "", timestamp_ms: 0, end_ms: 0, speaker: "张三", text, text_corrected: corrected,
});

const blocks: MergedBlock[] = [
  {
    id: "b1", speaker: "张三", startMs: 65_000, endMs: 70_000,
    sentences: [entry("原文一", "修正一"), entry("原文二", "修正二")],
  },
  {
    id: "b2", speaker: "李四", startMs: 90_000, endMs: 95_000,
    sentences: [entry("原文三", "修正三")],
  },
];

describe("buildPdfLines", () => {
  it("starts with a centered title line", () => {
    const lines = buildPdfLines(blocks, "corrected", "转录文稿");
    expect(lines[0]).toMatchObject({ text: "转录文稿", align: "center" });
  });

  it("emits a speaker+time header followed by the joined corrected text, per block", () => {
    const lines = buildPdfLines(blocks, "corrected", "t");
    expect(lines[1].text).toBe("张三  01:05");
    expect(lines[2].text).toBe("修正一修正二");
    expect(lines[3].text).toBe("李四  01:30");
    expect(lines[4].text).toBe("修正三");
  });

  it("can use the original (uncorrected) text instead", () => {
    const lines = buildPdfLines(blocks, "original", "t");
    expect(lines[2].text).toBe("原文一原文二");
  });

  it("body and header lines are left-aligned, unlike the title", () => {
    const lines = buildPdfLines(blocks, "corrected", "t");
    expect(lines[1].align).toBeUndefined();
    expect(lines[2].align).toBeUndefined();
  });
});
