import client from "./client";

export interface SynthesisResponse {
  audio_url: string;
  duration_ms: number;
  synthesis_time_ms: number;
}

export async function synthesizeTask(
  taskId: string,
  voiceMap?: Record<string, string>,
): Promise<SynthesisResponse> {
  const { data } = await client.post<SynthesisResponse>(
    `/tasks/${taskId}/synthesize`,
    { voice_map: voiceMap ?? null },
  );
  return data;
}

export function getSynthesisAudioUrl(taskId: string): string {
  return `/api/v1/tasks/${taskId}/synthesis`;
}
