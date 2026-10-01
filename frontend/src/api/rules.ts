import client from "./client";
import type { CustomRule, CustomRuleInput } from "../types/rules";

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
