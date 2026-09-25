import { describe, expect, it } from "vitest";
import { generateSrt } from "./srtGenerator";
import type { TranscriptEntry } from "../types/transcript";

const entries: TranscriptEntry[] = [
  { timestamp: "", timestamp_ms: 0, end_ms: 1500, speaker: "张三", text: "原文一", text_corrected: "修正一" },
  { timestamp: "", timestamp_ms: 2000, end_ms: 0, speaker: "李四", text: "原文二", text_corrected: "修正二" },
];

describe("generateSrt", () => {
  it("uses corrected text and the (renamed) speaker label by default", () => {
    const srt = generateSrt(entries);
    expect(srt).toContain("1\n00:00:00,000 --> 00:00:01,500\n张三: 修正一");
  });

  it("can export the original text", () => {
    expect(generateSrt(entries, "original")).toContain("张三: 原文一");
  });

  it("falls back to 5s duration when the last entry has no end time", () => {
    expect(generateSrt(entries)).toContain("00:00:02,000 --> 00:00:07,000");
  });
});
