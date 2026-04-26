import client from "../api/client";
import type { TaskSubmitResponse } from "../types/task";

const CHUNK_SIZE = 5 * 1024 * 1024;   // 5 MB
const MAX_CHUNK_RETRIES = 3;

interface ChunkUploadOptions {
    hotwords?: string;
    visualScan?: boolean;
    onProgress?: (received: number, total: number) => void;
}

interface QueryResponse {
    offset: number;
    complete: boolean;
    task_id: string | null;
}

interface ChunkResponse {
    received: number;
    complete: boolean;
    task_id: string | null;
}

function isRetryable(err: unknown): boolean {
    if (!(err instanceof Error)) return false;
    const statusCode = (err as Error & { statusCode?: number }).statusCode;
    return statusCode === undefined || statusCode >= 500;
}

function buildQueryParams(file: File, options?: ChunkUploadOptions): URLSearchParams {
    const params = new URLSearchParams({
        filename: file.name,
        total_size: String(file.size),
        visual_scan: String(options?.visualScan ?? false),
    });
    if (options?.hotwords) {
        try {
            const words = JSON.parse(options.hotwords) as string[];
            words.forEach((w) => params.append("hotwords", w));
        } catch {
            params.append("hotwords", options.hotwords);
        }
    }
    return params;
}

async function queryUploadState(
    hash: string,
    file: File,
    options?: ChunkUploadOptions,
): Promise<QueryResponse> {
    const params = buildQueryParams(file, options);
    const { data } = await client.get<QueryResponse>(`/uploads/${hash}?${params}`);
    return data;
}

async function sendChunk(
    hash: string,
    offset: number,
    end: number,
    total: number,
    buffer: ArrayBuffer,
): Promise<ChunkResponse> {
    const { data } = await client.patch<ChunkResponse>(
        `/uploads/${hash}`,
        buffer,
        {
            headers: {
                "Content-Type": "application/octet-stream",
                "Content-Range": `bytes ${offset}-${end}/${total}`,
            },
        },
    );
    return data;
}

export async function chunkedUploadFile(
    file: File,
    hash: string,
    options?: ChunkUploadOptions,
): Promise<TaskSubmitResponse> {
    // 服务端判断：已完成 / 断点续传 / 新上传
    const state = await queryUploadState(hash, file, options);

    if (state.complete) {
        return { task_id: state.task_id!, status: "completed", existing: true };
    }

    let offset = state.offset;
    options?.onProgress?.(offset, file.size);

    while (offset < file.size) {
        const slice = file.slice(offset, offset + CHUNK_SIZE);
        const buffer = await slice.arrayBuffer();
        const end = offset + buffer.byteLength - 1;

        let resp: ChunkResponse | null = null;
        let lastError: Error = new Error("分块上传失败");

        for (let attempt = 0; attempt < MAX_CHUNK_RETRIES; attempt++) {
            if (attempt > 0) {
                // 重试前查询服务端 offset：避免重复上传已收到的块
                try {
                    const retryState = await queryUploadState(hash, file, options);
                    if (retryState.complete) {
                        return { task_id: retryState.task_id!, status: "completed", existing: false };
                    }
                    if (retryState.offset > offset) {
                        offset = retryState.offset;
                        options?.onProgress?.(offset, file.size);
                        resp = { received: retryState.offset, complete: false, task_id: null };
                        break;
                    }
                } catch {
                    // 查询失败则继续重试上传
                }
                await new Promise((r) => setTimeout(r, 2 ** attempt * 1000));
            }

            try {
                resp = await sendChunk(hash, offset, end, file.size, buffer);
                break;
            } catch (err) {
                lastError = err instanceof Error ? err : new Error(String(err));
                if (!isRetryable(err)) throw err;
            }
        }

        if (resp === null) throw lastError;

        if (resp.received > offset) {
            offset = resp.received;
            options?.onProgress?.(offset, file.size);
        }

        if (resp.complete) {
            return { task_id: resp.task_id!, status: "pending", existing: false };
        }
    }

    throw new Error("所有分块已上传，但服务端未返回 task_id");
}
