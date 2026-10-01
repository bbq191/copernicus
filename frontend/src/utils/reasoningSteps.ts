/** 把 AI 判定逻辑的说明文本按中文句号/分号拆成步骤，供逐条展示。 */
export function splitReasoningSteps(reasoning: string): string[] {
  return reasoning
    .split(/[。；]/)
    .map((step) => step.trim())
    .filter(Boolean);
}
