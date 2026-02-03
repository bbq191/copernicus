import client from "./client";
import type { EvaluationResult } from "../types/evaluation";

export async function evaluateText(text: string): Promise<EvaluationResult> {
  const form = new FormData();
  form.append("text", text);
  const { data } = await client.post<EvaluationResult>("/evaluate/text", form);
  return data;
}
