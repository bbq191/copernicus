/** 后端错误响应转换成的 Error：statusCode 缺失表示没有收到响应（网络中断、超时）。 */
export class ApiError extends Error {
  readonly statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
  }
}

/** 网络中断、超时、5xx、429 属于可恢复错误；其余 4xx（如 404/422）重试无意义。 */
export function isTransientError(err: unknown): boolean {
  const code = (err as { statusCode?: number } | undefined)?.statusCode;
  return code === undefined || code >= 500 || code === 429;
}

/** 取出可展示给用户的错误文本。 */
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}
