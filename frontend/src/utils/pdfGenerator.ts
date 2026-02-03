import { jsPDF } from "jspdf";
import html2canvas from "html2canvas-pro";
import type { MergedBlock } from "../types/view";
import { formatTime } from "./formatTime";

/**
 * 使用 jspdf + html2canvas-pro 导出 PDF。
 * html2canvas-pro 原生支持 oklch 颜色函数，解决 DaisyUI/Tailwind v4 兼容问题。
 */
export async function exportToPdf(
  blocks: MergedBlock[],
  speakerMap: Record<string, string>,
  mode: "original" | "corrected" = "corrected",
  title = "转录文稿",
) {
  const container = document.createElement("div");
  container.style.cssText =
    "position:fixed;left:-9999px;top:0;width:794px;" +
    "font-family:sans-serif;color:#1a1a1a;background:#fff;padding:40px;";

  const h1 = document.createElement("h1");
  h1.textContent = title;
  h1.style.cssText =
    "text-align:center;font-size:20px;margin-bottom:24px;color:#1a1a1a;";
  container.appendChild(h1);

  for (const block of blocks) {
    const speaker = speakerMap[block.speaker] ?? block.speaker;
    const time = formatTime(block.startMs);

    const wrapper = document.createElement("div");
    wrapper.style.cssText = "margin-top:16px;";

    const header = document.createElement("p");
    header.style.cssText = "margin:0 0 4px 0;font-size:12px;color:#1a1a1a;";
    header.innerHTML =
      `<strong>${esc(speaker)}</strong>` +
      ` <span style="color:#888;font-size:11px;">${time}</span>`;
    wrapper.appendChild(header);

    const text = block.sentences
      .map((s) => (mode === "corrected" ? s.text_corrected : s.text))
      .join("");
    const p = document.createElement("p");
    p.textContent = text;
    p.style.cssText = "margin:0;font-size:12px;line-height:1.8;color:#333;";
    wrapper.appendChild(p);

    container.appendChild(wrapper);
  }

  document.body.appendChild(container);

  try {
    const canvas = await html2canvas(container, {
      scale: 2,
      scrollX: 0,
      scrollY: 0,
      useCORS: true,
      backgroundColor: "#ffffff",
    });

    const imgData = canvas.toDataURL("image/png");

    const pdf = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const margin = 10;
    const contentWidth = pageWidth - margin * 2;
    const contentHeight = (canvas.height * contentWidth) / canvas.width;

    let heightLeft = contentHeight;
    let position = margin;

    pdf.addImage(imgData, "PNG", margin, position, contentWidth, contentHeight);
    heightLeft -= pageHeight - margin * 2;

    while (heightLeft > 0) {
      position -= pageHeight - margin * 2;
      pdf.addPage();
      pdf.addImage(imgData, "PNG", margin, position, contentWidth, contentHeight);
      heightLeft -= pageHeight - margin * 2;
    }

    pdf.save(`${title}.pdf`);
  } finally {
    document.body.removeChild(container);
  }
}

function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
