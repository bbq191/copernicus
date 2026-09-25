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

// 健康检查应当快速返回；后端卡住时不要沿用全局 10 分钟超时，否则轮询请求会越积越多
const HEALTH_TIMEOUT_MS = 8000;

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health", { timeout: HEALTH_TIMEOUT_MS });
  return data;
}
