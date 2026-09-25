import { beforeEach, describe, expect, it } from "vitest";
import { useTranscriptStore } from "./transcriptStore";
import type { TranscriptEntry } from "../types/transcript";

const entry = (speaker: string, ms: number, text: string): TranscriptEntry => ({
  timestamp: "",
  timestamp_ms: ms,
  end_ms: ms + 500,
  speaker,
  text,
  text_corrected: text,
});

const load = () =>
  useTranscriptStore
    .getState()
    .setRawEntries([entry("Speaker 1", 0, "甲"), entry("Speaker 2", 1000, "乙"), entry("Speaker 1", 2000, "丙")]);

describe("transcriptStore", () => {
  beforeEach(() => useTranscriptStore.getState().setRawEntries([]));

  it("lists speakers in order of first appearance and shows them all", () => {
    load();
    const s = useTranscriptStore.getState();
    expect(s.speakers).toEqual(["Speaker 1", "Speaker 2"]);
    expect([...s.visibleSpeakers]).toEqual(["Speaker 1", "Speaker 2"]);
  });

  it("setSentenceText updates only the corrected text of one entry and rebuilds blocks", () => {
    load();
    useTranscriptStore.getState().setSentenceText(1, "改后");

    const s = useTranscriptStore.getState();
    expect(s.rawEntries[1].text_corrected).toBe("改后");
    expect(s.rawEntries[1].text).toBe("乙");
    expect(s.rawEntries[0].text_corrected).toBe("甲");
    expect(s.mergedBlocks[1].sentences[0].text_corrected).toBe("改后");
  });

  it("keeps identity of untouched entries so later edits can still find them", () => {
    load();
    const before = useTranscriptStore.getState().rawEntries;
    useTranscriptStore.getState().setSentenceText(1, "改后");
    const after = useTranscriptStore.getState().rawEntries;
    expect(after[0]).toBe(before[0]);
    expect(after[2]).toBe(before[2]);
  });

  it("renames a speaker everywhere", () => {
    load();
    useTranscriptStore.getState().applySpeakerRenames({ "Speaker 1": "张三" });

    const s = useTranscriptStore.getState();
    expect(s.rawEntries.map((e) => e.speaker)).toEqual(["张三", "Speaker 2", "张三"]);
    expect(s.speakers).toEqual(["张三", "Speaker 2"]);
    expect(s.visibleSpeakers.has("张三")).toBe(true);
    expect(s.visibleSpeakers.has("Speaker 1")).toBe(false);
  });

  it("merges speakers renamed to the same name into one block run", () => {
    load();
    useTranscriptStore.getState().applySpeakerRenames({ "Speaker 1": "张三", "Speaker 2": "张三" });

    const s = useTranscriptStore.getState();
    expect(s.speakers).toEqual(["张三"]);
    expect(s.mergedBlocks).toHaveLength(1);
  });

  it("a merged speaker stays visible if any source speaker was visible", () => {
    load();
    useTranscriptStore.getState().toggleSpeakerVisibility("Speaker 2"); // 隐藏 Speaker 2
    useTranscriptStore.getState().applySpeakerRenames({ "Speaker 1": "张三", "Speaker 2": "张三" });

    expect(useTranscriptStore.getState().visibleSpeakers.has("张三")).toBe(true);
  });

  it("a hidden speaker stays hidden after being renamed", () => {
    load();
    useTranscriptStore.getState().toggleSpeakerVisibility("Speaker 2");
    useTranscriptStore.getState().applySpeakerRenames({ "Speaker 2": "李四" });

    const { visibleSpeakers } = useTranscriptStore.getState();
    expect(visibleSpeakers.has("李四")).toBe(false);
    expect(visibleSpeakers.has("Speaker 1")).toBe(true);
  });
});
