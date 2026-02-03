import client from "./client";
import type { HealthResponse } from "../types/transcript";

export async function checkHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health");
  return data;
}
