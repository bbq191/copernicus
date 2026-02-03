import type { TranscriptEntry } from "../types/transcript";
import { formatTimeSrt } from "./formatTime";

export function generateSrt(
  entries: TranscriptEntry[],
  mode: "original" | "corrected" = "corrected",
): string {
  const lines: string[] = [];

  entries.forEach((entry, idx) => {
    const startMs = entry.timestamp_ms;
    const endMs =
      idx + 1 < entries.length
        ? entries[idx + 1].timestamp_ms
        : startMs + 5000;
    const text = mode === "corrected" ? entry.text_corrected : entry.text;

    lines.push(`${idx + 1}`);
    lines.push(`${formatTimeSrt(startMs)} --> ${formatTimeSrt(endMs)}`);
    lines.push(`${entry.speaker}: ${text}`);
    lines.push("");
  });

  return lines.join("\n");
}

export function downloadSrt(content: string, filename = "transcript.srt") {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
