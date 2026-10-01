import type { MergedBlock } from "../types/view";

/** 按模式拼接一个转写块内全部句子的文本（原文 or 纠错后）。 */
export function mergedBlockText(block: MergedBlock, mode: "original" | "corrected"): string {
  return block.sentences.map((s) => (mode === "corrected" ? s.text_corrected : s.text)).join("");
}
