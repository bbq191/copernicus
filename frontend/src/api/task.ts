import client from "./client";
import type { TaskSubmitResponse, TaskStatusResponse } from "../types/task";

export async function submitTranscriptTask(
  file: File,
  hotwords?: string,
): Promise<TaskSubmitResponse> {
  const form = new FormData();
  form.append("file", file);
  if (hotwords) form.append("hotwords", hotwords);
  const { data } = await client.post<TaskSubmitResponse>(
    "/tasks/transcript",
    form,
  );
  return data;
}

export async function getTaskStatus(
  taskId: string,
): Promise<TaskStatusResponse> {
  const { data } = await client.get<TaskStatusResponse>(`/tasks/${taskId}`);
  return data;
}
