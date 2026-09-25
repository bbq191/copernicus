import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 600_000,
  maxBodyLength: Infinity,
  maxContentLength: Infinity,
});

/** FastAPI 的 422 校验错误 detail 是数组（[{loc, msg, ...}]），直接放进 Error 会显示成 [object Object] */
function describeDetail(detail: unknown): string | undefined {
  if (detail == null) return undefined;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d?.msg === "string" ? d.msg : JSON.stringify(d)))
      .join("；");
  }
  return JSON.stringify(detail);
}

client.interceptors.response.use(
  (res) => res,
  (error) => {
    const message = describeDetail(error.response?.data?.detail) ?? error.message ?? "请求失败";
    const apiError = new Error(message) as Error & { statusCode?: number };
    apiError.statusCode = error.response?.status;
    return Promise.reject(apiError);
  },
);

export const POLL_INTERVAL_MS = 2000;

export const taskMediaUrl = (taskId: string) => `/api/v1/tasks/${taskId}/media`;
export const taskFrameUrl = (taskId: string, filename: string) =>
  `/api/v1/tasks/${taskId}/frames/${filename}`;
export const taskSynthesisAudioUrl = (taskId: string) =>
  `/api/v1/tasks/${taskId}/synthesis`;

export default client;
