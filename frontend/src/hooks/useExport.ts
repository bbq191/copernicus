import { useCallback, useState } from "react";
import { useTranscriptStore } from "../stores/transcriptStore";
import { useToastStore } from "../stores/toastStore";
import { generateSrt, downloadSrt } from "../utils/srtGenerator";
import { errorMessage } from "../api/errors";

type ExportFormat = "srt" | "word" | "pdf";

export function useExport() {
  const [isExporting, setIsExporting] = useState(false);
  const rawEntries = useTranscriptStore((s) => s.rawEntries);
  const mergedBlocks = useTranscriptStore((s) => s.mergedBlocks);
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
          // Word/PDF 依赖 docx、jspdf、html2canvas 等大体积库，按需加载
          case "word": {
            const { exportToWord } = await import("../utils/wordGenerator");
            await exportToWord(mergedBlocks, textMode);
            break;
          }
          case "pdf": {
            const { exportToPdf } = await import("../utils/pdfGenerator");
            await exportToPdf(mergedBlocks, textMode);
            break;
          }
        }
        const labels = { srt: "SRT 字幕", word: "Word 文档", pdf: "PDF 文档" };
        useToastStore.getState().addToast("success", `${labels[format]}导出成功`);
      } catch (err) {
        useToastStore
          .getState()
          .addToast("error", errorMessage(err, "导出失败"));
      } finally {
        setIsExporting(false);
      }
    },
    [rawEntries, mergedBlocks, textMode],
  );

  return { isExporting, exportAs };
}
