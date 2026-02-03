import {
  Document,
  Paragraph,
  TextRun,
  Packer,
  HeadingLevel,
  AlignmentType,
} from "docx";
import { saveAs } from "file-saver";
import type { MergedBlock } from "../types/view";
import { formatTime } from "./formatTime";

export async function exportToWord(
  blocks: MergedBlock[],
  speakerMap: Record<string, string>,
  mode: "original" | "corrected" = "corrected",
  title = "转录文稿",
) {
  const children: Paragraph[] = [
    new Paragraph({
      text: title,
      heading: HeadingLevel.HEADING_1,
      alignment: AlignmentType.CENTER,
    }),
    new Paragraph({ text: "" }),
  ];

  for (const block of blocks) {
    const speaker = speakerMap[block.speaker] ?? block.speaker;
    const time = formatTime(block.startMs);

    children.push(
      new Paragraph({
        children: [
          new TextRun({ text: `${speaker}`, bold: true }),
          new TextRun({ text: `  ${time}`, italics: true, color: "888888" }),
        ],
        spacing: { before: 240 },
      }),
    );

    const text = block.sentences
      .map((s) => (mode === "corrected" ? s.text_corrected : s.text))
      .join("");

    children.push(new Paragraph({ text }));
  }

  const doc = new Document({
    sections: [{ children }],
  });

  const blob = await Packer.toBlob(doc);
  saveAs(blob, `${title}.docx`);
}
