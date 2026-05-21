import client from "./client";

export interface ComponentStatus {
  status: "ok" | "degraded" | "down";
  detail?: string | null;
}

export interface TaskStats {
  active: number;
  completed: number;
  failed: number;
  synthesis_running: number;
}

export interface VramStatus {
  loaded_models: string[];
  estimated_used_gb: number;
  budget_gb: number;
}

export interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  asr: ComponentStatus;
  llm: ComponentStatus;
  tts: ComponentStatus | null;
  tasks: TaskStats;
  vram: VramStatus | null;
}

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health");
  return data;
}
