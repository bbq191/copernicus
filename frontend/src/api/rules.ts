import client from "./client";
import type { CustomRule, CustomRuleInput, ReauditJobStatus } from "../types/rules";

export async function listRules(): Promise<CustomRule[]> {
  const { data } = await client.get<CustomRule[]>("/rules");
  return data;
}

export async function createRule(input: CustomRuleInput): Promise<CustomRule> {
  const { data } = await client.post<CustomRule>("/rules", input);
  return data;
}

export async function updateRule(
  id: number,
  patch: Partial<CustomRuleInput>,
): Promise<CustomRule> {
  const { data } = await client.patch<CustomRule>(`/rules/${id}`, patch);
  return data;
}

export async function deleteRule(id: number): Promise<void> {
  await client.delete(`/rules/${id}`);
}

/** 查询有多少历史任务（经规则库提交审核的）引用过这条规则。 */
export async function countAffectedTasks(
  ruleId: number,
): Promise<{ task_ids: string[]; total: number }> {
  const { data } = await client.get<{ task_ids: string[]; total: number }>(
    `/rules/${ruleId}/affected-tasks`,
  );
  return data;
}

/** 发起批量重审，立即返回 job_id；用 getReauditJob 轮询进度。 */
export async function startReaudit(ruleId: number): Promise<{ job_id: string; total: number }> {
  const { data } = await client.post<{ job_id: string; total: number }>(
    `/rules/${ruleId}/reaudit-affected`,
  );
  return data;
}

export async function getReauditJob(jobId: string): Promise<ReauditJobStatus> {
  const { data } = await client.get<ReauditJobStatus>(`/rules/reaudit-jobs/${jobId}`);
  return data;
}
