import { createSHA256 } from "hash-wasm";

const HASH_CHUNK_SIZE = 8 * 1024 * 1024; // 8 MB，避免大文件整体读入内存

export async function computeFileSHA256(file: File): Promise<string> {
    const hasher = await createSHA256();
    hasher.init();
    for (let offset = 0; offset < file.size; offset += HASH_CHUNK_SIZE) {
        const chunk = await file.slice(offset, offset + HASH_CHUNK_SIZE).arrayBuffer();
        hasher.update(new Uint8Array(chunk));
    }
    return hasher.digest("hex");
}
