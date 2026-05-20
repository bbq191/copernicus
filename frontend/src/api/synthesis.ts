import client, { taskSynthesisAudioUrl } from "./client";

export interface SynthesisStatusResponse {
  status: "running" | "completed" | "failed";
  error?: string | null;
  audio_url?: string | null;
  duration_ms?: number | null;
  synthesis_time_ms?: number | null;
}

export async function startSynthesis(
  taskId: string,
  voiceMap?: Record<string, string>,
): Promise<void> {
  await client.post(`/tasks/${taskId}/synthesize`, {
    voice_map: voiceMap ?? null,
  });
}

export async function getSynthesisStatus(
  taskId: string,
): Promise<SynthesisStatusResponse> {
  const { data } = await client.get<SynthesisStatusResponse>(
    `/tasks/${taskId}/synthesis/status`,
  );
  return data;
}

export function getSynthesisAudioUrl(taskId: string): string {
  return taskSynthesisAudioUrl(taskId);
}
