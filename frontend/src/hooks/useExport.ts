import { useCallback, useState } from "react";
import { useTranscriptStore } from "../stores/transcriptStore";
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
      } finally {
        setIsExporting(false);
      }
    },
    [rawEntries, mergedBlocks, speakerMap, textMode],
  );

  return { isExporting, exportAs };
}
