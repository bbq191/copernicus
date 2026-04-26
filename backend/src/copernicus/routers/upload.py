"""分片上传接口：GET 查询/创建会话 → PATCH 分块上传 → 自动触发转写任务。"""

import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from copernicus.config import settings
from copernicus.dependencies import get_task_store, get_upload_session_service
from copernicus.schemas.upload import UploadChunkResponse, UploadQueryResponse
from copernicus.services.task_store import TaskStore
from copernicus.services.upload_session import UploadSessionService

_VIDEO_EXTENSIONS = {
    e.strip().lower()
    for e in settings.video_extensions.split(",")
    if e.strip()
}

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


@router.get("/{file_hash}", response_model=UploadQueryResponse)
async def query_upload(
    file_hash: str,
    filename: str,
    total_size: int,
    hotwords: Annotated[list[str] | None, Query()] = None,
    visual_scan: bool = False,
    store: TaskStore = Depends(get_task_store),
    upload_sessions: UploadSessionService = Depends(get_upload_session_service),
) -> UploadQueryResponse:
    """查询上传状态；若会话不存在则自动创建（幂等）。

    - 文件已处理完成：返回 complete=True + task_id
    - 会话已有部分数据：返回当前 offset（断点续传）
    - 全新文件：创建会话并返回 offset=0
    """
    if total_size > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    existing_id = store.lookup_by_hash(file_hash)
    if existing_id:
        return UploadQueryResponse(offset=total_size, complete=True, task_id=existing_id)

    offset = upload_sessions.get_or_create(
        file_hash=file_hash,
        filename=filename,
        total_size=total_size,
        hotwords=hotwords or None,
        visual_scan=visual_scan,
    )
    return UploadQueryResponse(offset=offset, complete=False)


@router.patch("/{file_hash}", response_model=UploadChunkResponse)
async def upload_chunk(
    file_hash: str,
    request: Request,
    store: TaskStore = Depends(get_task_store),
    upload_sessions: UploadSessionService = Depends(get_upload_session_service),
) -> UploadChunkResponse:
    """接收数据块并追加。最后一块到达后校验 SHA-256，通过则自动创建转写任务。

    请求头：Content-Range: bytes {start}-{end}/{total}
    请求体：raw binary（application/octet-stream）
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

    session = upload_sessions.get_session(file_hash)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Upload session not found — call GET /uploads/{hash} first",
        )

    try:
        new_offset, complete = upload_sessions.append_chunk(file_hash, offset, chunk)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not complete:
        return UploadChunkResponse(received=new_offset, complete=False)

    # --- 最后一块：组装、校验、提交任务 ---
    assembled = upload_sessions.read_assembled(file_hash)

    actual_hash = hashlib.sha256(assembled).hexdigest()
    if actual_hash != session["hash"]:
        upload_sessions.delete_session(file_hash)
        raise HTTPException(
            status_code=422,
            detail=f"SHA-256 mismatch: expected {session['hash']}, got {actual_hash}",
        )

    filename: str = session["filename"]
    hotwords: list[str] | None = session["hotwords"] or None
    visual_scan: bool = session["visual_scan"]

    # 竞态保护：两次并发上传同一文件只处理一次
    existing_id = store.lookup_by_hash(file_hash)
    if existing_id:
        upload_sessions.delete_session(file_hash)
        return UploadChunkResponse(received=new_offset, complete=True, task_id=existing_id)

    task_id = store.submit_transcript(
        assembled, filename, hotwords,
        file_hash=file_hash,
        visual_scan=visual_scan,
    )

    persistence = store.persistence
    suffix = Path(filename).suffix or ".bin"
    is_video = suffix.lower() in _VIDEO_EXTENSIONS
    if is_video:
        video_path = persistence.save_video(task_id, assembled, suffix)
        persistence.save_meta(
            task_id,
            filename=filename,
            file_hash=file_hash,
            audio_suffix=suffix,
            media_type="video",
            video_suffix=suffix,
        )
        task = store.get(task_id)
        if task:
            task.audio_path = str(video_path)
    else:
        audio_path = persistence.save_audio(task_id, assembled, suffix)
        persistence.save_meta(
            task_id, filename=filename, file_hash=file_hash, audio_suffix=suffix
        )
        task = store.get(task_id)
        if task:
            task.audio_path = str(audio_path)

    upload_sessions.delete_session(file_hash)
    return UploadChunkResponse(received=new_offset, complete=True, task_id=task_id)
