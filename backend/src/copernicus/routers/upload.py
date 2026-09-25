"""分片上传接口：GET 查询/创建会话 → PATCH 分块上传 → 自动触发标准纪要任务。"""

import asyncio
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from copernicus.config import settings
from copernicus.dependencies import get_task_store, get_upload_session_service
from copernicus.schemas.upload import UploadChunkResponse, UploadQueryResponse
from copernicus.services.task_store import TaskStore
from copernicus.services.upload_session import UploadSessionService

router = APIRouter(prefix="/api/v1/uploads", tags=["存储层"])


@router.get(
    "/{file_hash}",
    response_model=UploadQueryResponse,
    summary="查询或创建上传会话",
)
async def query_upload(
    file_hash: str,
    filename: str,
    total_size: int,
    hotwords: Annotated[list[str] | None, Query()] = None,
    visual_scan: bool = False,
    generate_summary: bool = True,
    store: TaskStore = Depends(get_task_store),
    upload_sessions: UploadSessionService = Depends(get_upload_session_service),
) -> UploadQueryResponse:
    """上传前的幂等预检，返回当前断点偏移量。

    - 文件哈希已存在：返回 `complete=true` + `task_id`，无需重复上传。
    - 会话已有部分数据：返回当前 `offset`，客户端从此处续传。
    - 全新文件：创建会话并返回 `offset=0`。

    `file_hash` 为文件的 SHA-256 十六进制字符串。`visual_scan=true`
    时将在转写完成后额外执行关键帧 OCR 和人脸检测。
    """
    if total_size > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    existing_id = store.lookup_by_hash(file_hash)
    if existing_id:
        return UploadQueryResponse(offset=total_size, complete=True, task_id=existing_id)

    if upload_sessions.get_session(file_hash) is None:
        store.ensure_capacity()  # 队列已满时不再开启新的上传会话，已有会话仍可续传

    offset = upload_sessions.get_or_create(
        file_hash=file_hash,
        filename=filename,
        total_size=total_size,
        hotwords=hotwords or None,
        visual_scan=visual_scan,
        generate_summary=generate_summary,
    )
    return UploadQueryResponse(offset=offset, complete=False)


@router.patch(
    "/{file_hash}",
    response_model=UploadChunkResponse,
    summary="上传数据块",
)
async def upload_chunk(
    file_hash: str,
    request: Request,
    store: TaskStore = Depends(get_task_store),
    upload_sessions: UploadSessionService = Depends(get_upload_session_service),
) -> UploadChunkResponse:
    """追加一个数据块，最后一块到达后自动触发标准纪要任务。

    **请求头**：`Content-Range: bytes {start}-{end}/{total}`

    **请求体**：`application/octet-stream`（原始二进制）

    末块到达后执行 SHA-256 完整性校验；通过后调用
    `submit_standard_minutes`，返回 `task_id`，后续通过
    `GET /api/v1/tasks/{task_id}` 轮询处理进度。
    """
    content_range = request.headers.get("Content-Range", "")
    try:
        range_spec = content_range.removeprefix("bytes ")
        range_part, _ = range_spec.split("/")
        start, _ = range_part.split("-")
        offset = int(start)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid or missing Content-Range header")

    chunk = await request.body()
    if not chunk:
        raise HTTPException(status_code=400, detail="Empty chunk body")

    # 同一文件的分块串行处理：客户端重试/重复请求并发到达时避免交错写入
    async with upload_sessions.lock(file_hash):
        return await _handle_chunk(file_hash, offset, chunk, store, upload_sessions)


async def _handle_chunk(
    file_hash: str,
    offset: int,
    chunk: bytes,
    store: TaskStore,
    upload_sessions: UploadSessionService,
) -> UploadChunkResponse:
    session = upload_sessions.get_session(file_hash)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Upload session not found — call GET /uploads/{hash} first",
        )

    try:
        new_offset, complete = await asyncio.to_thread(
            upload_sessions.append_chunk, file_hash, offset, chunk
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not complete:
        return UploadChunkResponse(received=new_offset, complete=False)

    # --- 最后一块：组装、校验、提交任务（大文件读写与哈希放入线程，避免阻塞事件循环）---
    assembled, actual_hash = await asyncio.to_thread(_assemble_and_hash, upload_sessions, file_hash)
    if actual_hash != session["hash"]:
        upload_sessions.delete_session(file_hash)
        raise HTTPException(
            status_code=422,
            detail=f"SHA-256 mismatch: expected {session['hash']}, got {actual_hash}",
        )

    filename: str = session["filename"]

    # 竞态保护：两次并发上传同一文件只处理一次
    existing_id = store.lookup_by_hash(file_hash)
    if existing_id:
        upload_sessions.delete_session(file_hash)
        return UploadChunkResponse(received=new_offset, complete=True, task_id=existing_id)

    task_id = store.submit_standard_minutes(
        assembled, filename, session["hotwords"] or None,
        file_hash=file_hash,
        visual_scan=session["visual_scan"],
        generate_summary=session.get("generate_summary", True),
    )
    await asyncio.to_thread(store.attach_media, task_id, filename, file_hash, assembled)

    upload_sessions.delete_session(file_hash)
    return UploadChunkResponse(received=new_offset, complete=True, task_id=task_id)


def _assemble_and_hash(upload_sessions: UploadSessionService, file_hash: str) -> tuple[bytes, str]:
    assembled = upload_sessions.read_assembled(file_hash)
    return assembled, hashlib.sha256(assembled).hexdigest()
