import client from "./client";
import type {
  TaskSubmitResponse,
  TaskStatusResponse,
  TaskResultsResponse,
} from "../types/task";

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

export async function getTaskResults(
  taskId: string,
): Promise<TaskResultsResponse> {
  const { data } = await client.get<TaskResultsResponse>(
    `/tasks/${taskId}/results`,
  );
  return data;
}

export async function rerunTranscript(
  taskId: string,
): Promise<TaskSubmitResponse> {
  const { data } = await client.post<TaskSubmitResponse>(
    `/tasks/${taskId}/rerun-transcript`,
  );
  return data;
}

export async function rerunEvaluation(
  taskId: string,
): Promise<TaskSubmitResponse> {
  const { data } = await client.post<TaskSubmitResponse>(
    `/tasks/${taskId}/rerun-evaluation`,
  );
  return data;
}
