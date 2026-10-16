export type RuleCategory = "forbidden_phrase" | "behavioral" | "document" | "visual_check";
export type CheckMode = "exact" | "semantic" | "visual";
export type EvidenceSource = "transcript" | "ocr" | "vision";
export type RuleSeverity = "high" | "medium" | "low";

/** 与后端 CustomRuleBase（schemas/compliance.py）的字段长度约束保持一致 */
export const RULE_TITLE_MAX_LEN = 100;
export const RULE_CONTENT_MAX_LEN = 2000;
export const RULE_DESCRIPTION_MAX_LEN = 2000;

export interface CustomRule {
  id: number;
  title: string;
  content: string;
  category: RuleCategory;
  check_mode: CheckMode;
  evidence_sources: EvidenceSource[];
  keywords: string[];
  description: string;
  severity_default: RuleSeverity;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type CustomRuleInput = Omit<CustomRule, "id" | "created_at" | "updated_at">;

export interface ReauditDiff {
  task_id: string;
  old_score: number;
  new_score: number;
}

/** 规则变更后批量重审的进度；done 之前前端按固定间隔轮询。 */
export interface ReauditJobStatus {
  id: string;
  rule_id: number;
  total: number;
  completed: number;
  failed: string[];
  done: boolean;
  diffs: ReauditDiff[];
}
