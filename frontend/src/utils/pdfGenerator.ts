import type { MergedBlock } from "../types/view";
import { formatTime } from "./formatTime";

/**
 * 真文字 PDF 导出：用 jsPDF 的文本 API 直接画字，不再截图 DOM。
 *
 * jsPDF 内置字体不含中文字形，所以需要嵌入 public/fonts/ 下的 Noto Sans CJK SC
 * 子集（仅拉丁字母+常用标点+CJK 统一表意文字，见该目录的 NOTICE.md）；
 * jsPDF 生成时还会按文档实际用到的字符再次子集化，单个 PDF 不会携带整个字库。
 */
const FONT_URL = "/fonts/NotoSansSC-subset.ttf";
const FONT_NAME = "NotoSansSC";

const PAGE_WIDTH_MM = 210;
const PAGE_HEIGHT_MM = 297;
const MARGIN_MM = 18;
const CONTENT_WIDTH_MM = PAGE_WIDTH_MM - MARGIN_MM * 2;
const MM_PER_PT = 25.4 / 72;
const LINE_HEIGHT_FACTOR = 1.4;

const TITLE_SIZE_PT = 18;
const HEADER_SIZE_PT = 10.5;
const BODY_SIZE_PT = 11;

const COLOR_TITLE: [number, number, number] = [26, 26, 26];
const COLOR_HEADER: [number, number, number] = [80, 80, 80];
const COLOR_BODY: [number, number, number] = [26, 26, 26];

interface PdfLine {
  text: string;
  sizePt: number;
  color: [number, number, number];
  /** 与上一行之间的额外间距（mm），仅在该逻辑行的第一个换行行前生效 */
  gapBeforeMm: number;
  align?: "left" | "center";
}

/** 纯逻辑：把转写块铺成待渲染的行，不依赖 jsPDF/DOM，可直接单测。 */
export function buildPdfLines(
  blocks: MergedBlock[],
  mode: "original" | "corrected",
  title: string,
): PdfLine[] {
  const lines: PdfLine[] = [
    { text: title, sizePt: TITLE_SIZE_PT, color: COLOR_TITLE, gapBeforeMm: 0, align: "center" },
  ];
  for (const block of blocks) {
    const text = block.sentences
      .map((s) => (mode === "corrected" ? s.text_corrected : s.text))
      .join("");
    lines.push({
      text: `${block.speaker}  ${formatTime(block.startMs)}`,
      sizePt: HEADER_SIZE_PT,
      color: COLOR_HEADER,
      gapBeforeMm: 6,
    });
    lines.push({ text, sizePt: BODY_SIZE_PT, color: COLOR_BODY, gapBeforeMm: 1.5 });
  }
  return lines;
}

let cachedFontBase64: Promise<string> | null = null;

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000; // 分块拼接，避免 String.fromCharCode(...bytes) 在大数组上栈溢出
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

/** 字体只需加载一次；加载失败不缓存，允许用户重新点击导出时重试。 */
async function loadFontBase64(): Promise<string> {
  cachedFontBase64 ??= fetch(FONT_URL)
    .then((res) => {
      if (!res.ok) throw new Error(`字体加载失败（HTTP ${res.status}）`);
      return res.arrayBuffer();
    })
    .then(arrayBufferToBase64);
  try {
    return await cachedFontBase64;
  } catch (err) {
    cachedFontBase64 = null;
    throw err;
  }
}

export async function exportToPdf(
  blocks: MergedBlock[],
  mode: "original" | "corrected" = "corrected",
  title = "转录文稿",
): Promise<void> {
  const [{ jsPDF }, fontBase64] = await Promise.all([import("jspdf"), loadFontBase64()]);

  const doc = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
  doc.addFileToVFS(`${FONT_NAME}.ttf`, fontBase64);
  doc.addFont(`${FONT_NAME}.ttf`, FONT_NAME, "normal");
  doc.setFont(FONT_NAME);

  let y = MARGIN_MM;
  for (const line of buildPdfLines(blocks, mode, title)) {
    const lineHeightMm = line.sizePt * MM_PER_PT * LINE_HEIGHT_FACTOR;
    doc.setFontSize(line.sizePt);
    doc.setTextColor(...line.color);
    const wrapped = doc.splitTextToSize(line.text, CONTENT_WIDTH_MM) as string[];

    wrapped.forEach((wrappedLine, i) => {
      const gap = i === 0 ? line.gapBeforeMm : 0;
      // 已经在页首时不再分页，避免长到超过一整页的段落产生空白页
      if (y + gap + lineHeightMm > PAGE_HEIGHT_MM - MARGIN_MM && y > MARGIN_MM) {
        doc.addPage();
        y = MARGIN_MM;
      } else {
        y += gap;
      }
      const x = line.align === "center" ? PAGE_WIDTH_MM / 2 : MARGIN_MM;
      doc.text(wrappedLine, x, y, line.align === "center" ? { align: "center" } : undefined);
      y += lineHeightMm;
    });
  }

  doc.save(`${title}.pdf`);
}
