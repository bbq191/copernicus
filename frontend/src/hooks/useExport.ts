import { useCallback, useState } from "react";
import { useTranscriptStore } from "../stores/transcriptStore";
import { useToastStore } from "../stores/toastStore";
import { generateSrt, downloadSrt } from "../utils/srtGenerator";
import { exportToWord } from "../utils/wordGenerator";
import { exportToPdf } from "../utils/pdfGenerator";

type ExportFormat = "srt" | "word" | "pdf";

export function useExport() {
  const [isExporting, setIsExporting] = useState(false);
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const mergedBlocks = useTranscriptStore((s) => s.mergedBlocks);
  const speakerMap = useTranscriptStore((s) => s.speakerMap);
  const textMode = useTranscriptStore((s) => s.textMode);

  const exportAs = useCallback(
    async (format: ExportFormat) => {
      setIsExporting(true);
      try {
        switch (format) {
          case "srt": {
            const content = generateSrt(rawEntries, textMode);
            downloadSrt(content);
            break;
          }
          case "word":
            await exportToWord(mergedBlocks, speakerMap, textMode);
            break;
          case "pdf":
            await exportToPdf(mergedBlocks, speakerMap, textMode);
            break;
        }
        const labels = { srt: "SRT 字幕", word: "Word 文档", pdf: "PDF 文档" };
        useToastStore.getState().addToast("success", `${labels[format]}导出成功`);
      } catch (err) {
        useToastStore
          .getState()
          .addToast("error", err instanceof Error ? err.message : "导出失败");
        throw err;
      } finally {
        setIsExporting(false);
      }
    },
    [rawEntries, mergedBlocks, speakerMap, textMode],
  );

  return { isExporting, exportAs };
}
