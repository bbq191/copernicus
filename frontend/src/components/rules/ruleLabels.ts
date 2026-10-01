import type { CheckMode, CustomRuleInput, EvidenceSource, RuleCategory, RuleSeverity } from "../../types/rules";

export const CATEGORY_LABEL: Record<RuleCategory, string> = {
  forbidden_phrase: "禁止用语",
  behavioral: "行为规范",
  document: "文件/资料要求",
  visual_check: "视觉检查",
};

export const CHECK_MODE_LABEL: Record<CheckMode, string> = {
  exact: "精确关键词匹配",
  semantic: "语义审核（LLM）",
  visual: "视觉审核（需 OCR）",
};

export const EVIDENCE_LABEL: Record<EvidenceSource, string> = {
  transcript: "转写文本",
  ocr: "画面文字",
  vision: "人脸检测",
};

export const SEVERITY_LABEL: Record<RuleSeverity, string> = { high: "高", medium: "中", low: "低" };
export const SEVERITY_BADGE: Record<RuleSeverity, string> = {
  high: "badge-error", medium: "badge-warning", low: "badge-info",
};

export const EMPTY_RULE_DRAFT: CustomRuleInput = {
  title: "", content: "", category: "behavioral", check_mode: "semantic",
  evidence_sources: ["transcript"], keywords: [], description: "", severity_default: "medium",
  enabled: true,
};
