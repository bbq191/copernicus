import axios from "axios";
import { ApiError } from "./errors";

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
    return Promise.reject(new ApiError(message, error.response?.status));
  },
);

export const POLL_INTERVAL_MS = 2000;

/**
 * PATCH 请求；keepalive=true 用于页面关闭前的最后一次提交——axios 不支持 keepalive，
 * 改用 fetch，浏览器会在页面卸载后继续发送，响应体按 JSON 解析为 T。
 */
export async function patchKeepalive<T>(
  url: string,
  body: unknown,
  keepalive: boolean,
): Promise<T> {
  if (!keepalive) {
    const { data } = await client.patch<T>(url, body);
    return data;
  }
  const res = await fetch(`${client.defaults.baseURL}${url}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true,
  });
  if (!res.ok) throw new Error(`保存失败（${res.status}）`);
  return (await res.json()) as T;
}

export const taskMediaUrl = (taskId: string) => `/api/v1/tasks/${taskId}/media`;
export const taskFrameUrl = (taskId: string, filename: string) =>
  `/api/v1/tasks/${taskId}/frames/${filename}`;
export const taskSynthesisAudioUrl = (taskId: string) =>
  `/api/v1/tasks/${taskId}/synthesis`;

export default client;
