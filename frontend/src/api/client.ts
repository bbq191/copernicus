import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 600_000,
  maxBodyLength: Infinity,
  maxContentLength: Infinity,
});

client.interceptors.response.use(
  (res) => res,
  (error) => {
    const message =
      error.response?.data?.detail ?? error.message ?? "请求失败";
    const apiError = new Error(message) as Error & { statusCode?: number };
    apiError.statusCode = error.response?.status;
    return Promise.reject(apiError);
  },
);

export const POLL_INTERVAL_MS = 2000;

export const taskUrl = (taskId: string) => `/tasks/${taskId}`;
export const taskMediaUrl = (taskId: string) => `/api/v1/tasks/${taskId}/media`;
export const taskFrameUrl = (taskId: string, filename: string) =>
  `/api/v1/tasks/${taskId}/frames/${filename}`;
export const taskSynthesisAudioUrl = (taskId: string) =>
  `/api/v1/tasks/${taskId}/synthesis`;

export default client;
