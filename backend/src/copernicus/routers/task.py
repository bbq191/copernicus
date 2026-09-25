import asyncio
import hashlib
import mimetypes
import re
from pathlib import Path
from typing import NamedTuple

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse

from copernicus.config import settings
from copernicus.dependencies import get_task_store
from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResult
from copernicus.schemas.task import (
    SpeakerRenameRequest,
    TaskListResponse,
    TaskRenameRequest,
    TaskStatus,
    TaskStatusResponse,
    TaskSubmitResponse,
    TaskResultsResponse,
    TranscriptEditRequest,
    TranscriptUpdateResponse,
)
from copernicus.schemas.transcription import TranscriptResponse
from copernicus.services.task_store import TaskStore
from copernicus.services.upload_session import incoming_path
from copernicus.utils.request import parse_hotwords

_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')

# 不设置 router 级 tags，各路由按逻辑层单独标注
router = APIRouter(prefix="/api/v1")


class _UploadResult(NamedTuple):
    path: Path | None          # 已落盘的上传文件（existing_response 存在时为 None）
    file_hash: str
    hotwords: list[str]
    filename: str
    existing_response: TaskSubmitResponse | None


_READ_CHUNK = 1024 * 1024


def _write_block(out, digest, chunk: bytes) -> None:
    digest.update(chunk)
    out.write(chunk)


async def _receive_upload(
    file: UploadFile,
    hotwords_str: str | None,
    store: TaskStore,
) -> _UploadResult:
    """把上传文件边读边写到磁盘并计算哈希，全程不整体载入内存。

    文件已存在（哈希命中）时丢弃临时文件，在 existing_response 中返回缓存响应。
    """
    limit = settings.max_upload_size_bytes
    if file.size is not None and file.size > limit:
        raise HTTPException(status_code=413, detail="File too large")

    dest = incoming_path(settings.upload_dir)
    digest = hashlib.sha256()
    received = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(_READ_CHUNK):
                received += len(chunk)
                if received > limit:
                    raise HTTPException(status_code=413, detail="File too large")
                await asyncio.to_thread(_write_block, out, digest, chunk)
        file_hash = digest.hexdigest()

        existing_id = store.lookup_by_hash(file_hash)
        if existing_id:
            existing_task = store.get(existing_id)
            existing_status = existing_task.status if existing_task else TaskStatus.COMPLETED
            dest.unlink(missing_ok=True)
            return _UploadResult(
                None, file_hash, [], "",
                TaskSubmitResponse(task_id=existing_id, status=existing_status, existing=True),
            )
        try:
            hw = parse_hotwords(hotwords_str)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return _UploadResult(dest, file_hash, hw, file.filename or "upload.bin", None)


# ---------------------------------------------------------------------------
# 基础 AI — 任务提交
# ---------------------------------------------------------------------------

@router.post(
    "/tasks/standard_minutes",
    response_model=TaskSubmitResponse,
    status_code=202,
    tags=["基础 AI"],
    summary="提交标准纪要任务（主入口）",
)
async def submit_standard_minutes_task(
    file: UploadFile = File(..., description="音频或视频文件，最大 500 MB"),
    hotwords: str | None = Form(default=None, description="热词列表，JSON 字符串数组，如 [\"公司名\"]"),
    visual_scan: bool = Form(default=False, description="是否提取关键帧并执行 OCR/人脸检测"),
    generate_summary: bool = Form(default=True, description="是否在转写完成后自动生成摘要"),
    template_id: str = Form(default="universal", description="纪要模板 ID，可通过 GET /api/v1/templates 查询可用列表"),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """上传音视频文件，执行完整的 Base AI 流水线。

    **流程**：ASR 转写（SenseVoice）→ 物理清洗 → LLM 文字纠错 → 智能摘要（Map-Reduce）

    重复上传同一文件（SHA-256 相同）时直接返回已有任务，`existing=true`。

    `visual_scan=true` 时额外执行关键帧提取、OCR 和人脸检测，结果存入
    `ocr_results.json` 与 `visual_events.json`，可供后续合规审核使用。
    """
    upload = await _receive_upload(file, hotwords, store)
    if upload.existing_response:
        return upload.existing_response
    task_id = await store.submit_standard_minutes(
        upload.path, upload.filename, upload.hotwords,
        file_hash=upload.file_hash,
        visual_scan=visual_scan,
        generate_summary=generate_summary,
        template_id=template_id,
    )
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.post(
    "/tasks/transcript",
    response_model=TaskSubmitResponse,
    status_code=202,
    tags=["基础 AI"],
    summary="提交转写任务（轻量，不含摘要）",
)
async def submit_transcript_task(
    file: UploadFile = File(..., description="音频或视频文件，最大 500 MB"),
    hotwords: str | None = Form(default=None, description="热词列表，JSON 字符串数组"),
    visual_scan: bool = Form(default=False, description="是否执行视觉扫描"),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """上传音视频文件，执行 ASR 转写 + 文字纠错，不生成摘要。

    比 `standard_minutes` 快约 30%（省去评估阶段的 LLM 调用）。
    适用于只需要转写文本、后续自行处理摘要的场景。
    """
    upload = await _receive_upload(file, hotwords, store)
    if upload.existing_response:
        return upload.existing_response
    task_id = await store.submit_transcript(
        upload.path, upload.filename, upload.hotwords,
        file_hash=upload.file_hash,
        visual_scan=visual_scan,
    )
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.post(
    "/tasks/{task_id}/rerun-transcript",
    response_model=TaskSubmitResponse,
    tags=["基础 AI"],
    summary="重新执行转写",
)
async def rerun_transcript(
    task_id: str,
    hotwords: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """对已保存的音频重新运行 ASR + 纠错流水线。

    原始媒体文件必须仍存在（未被生命周期清理）。
    执行后会清除旧的 `evaluation.json` 和 `compliance.json`，
    需重新提交评估或合规审核。
    """
    try:
        hw = parse_hotwords(hotwords)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    store.rerun_transcript(task_id, hw)
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)



# ---------------------------------------------------------------------------
# 任务管理 — 查询与媒体
# ---------------------------------------------------------------------------

@router.get(
    "/tasks",
    response_model=TaskListResponse,
    tags=["任务管理"],
    summary="历史任务列表",
)
async def list_tasks(
    limit: int = Query(default=100, ge=1, le=500),
    store: TaskStore = Depends(get_task_store),
) -> TaskListResponse:
    """按创建时间倒序返回历史任务摘要（含运行中与失败的任务）。

    `total` 为磁盘上的任务总数，大于返回条数时表示被 `limit` 截断。
    """
    # 需要遍历任务目录并逐个读取 meta.json，放入线程避免任务多时阻塞事件循环
    tasks, total = await asyncio.to_thread(store.list_tasks, limit)
    return TaskListResponse(tasks=tasks, total=total)


@router.patch(
    "/tasks/{task_id}",
    status_code=204,
    tags=["任务管理"],
    summary="重命名任务",
)
async def rename_task(
    task_id: str,
    body: TaskRenameRequest,
    store: TaskStore = Depends(get_task_store),
) -> None:
    """设置任务的显示名称，用于历史列表。"""
    store.rename_task(task_id, body.name.strip())


@router.delete(
    "/tasks/{task_id}",
    status_code=204,
    tags=["任务管理"],
    summary="作废任务缓存，或彻底删除任务",
)
async def delete_task(
    task_id: str,
    purge: bool = Query(default=False, description="true 时同时删除磁盘上的全部文件，不可恢复"),
    store: TaskStore = Depends(get_task_store),
) -> None:
    """默认仅从内存和哈希索引中移除任务缓存（`purge=false`）。

    清除后，使用相同文件重新调用 `POST /api/v1/tasks/standard_minutes`
    将触发完整流水线重新处理，而不是返回 `existing=true`；磁盘文件保留。

    `purge=true` 会彻底删除任务：原始媒体、转写、纪要、合规报告与关键帧全部移除，
    不可恢复。任务仍在运行时返回 409。
    """
    found = store.purge_task(task_id) if purge else store.invalidate_task(task_id)
    if not found:
        raise HTTPException(status_code=404, detail="Task not found")


@router.get(
    "/tasks/lookup",
    response_model=TaskSubmitResponse,
    tags=["任务管理"],
    summary="按文件哈希查询任务",
)
async def lookup_task_by_hash(
    hash: str,
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """根据文件 SHA-256 查询是否已有对应任务。

    用于上传前预检：若返回 200，说明文件已处理过，直接使用 `task_id` 获取结果，
    无需重新上传。返回 404 时再发起上传流程。
    """
    existing_id = store.lookup_by_hash(hash)
    if not existing_id:
        raise HTTPException(status_code=404, detail="Task not found")
    existing_task = store.get(existing_id)
    status = existing_task.status if existing_task else TaskStatus.COMPLETED
    return TaskSubmitResponse(task_id=existing_id, status=status, existing=True)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    tags=["任务管理"],
    summary="查询任务状态与进度",
)
async def get_task_status(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> TaskStatusResponse:
    """轮询任务的实时状态与进度百分比。

    `status` 状态机：`pending` → `processing_asr` / `extracting_frames` /
    `scanning_visual` → `correcting` → `evaluating` / `auditing` →
    `completed` / `failed`。

    `progress.percent` 为 0–100 的浮点数。任务完成后 `result` 字段包含
    最终结果（转写、评估或合规报告）。
    """
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        progress=task.progress,
        result=task.result,
        error=task.error,
    )


@router.get(
    "/tasks/{task_id}/results",
    response_model=TaskResultsResponse,
    tags=["任务管理"],
    summary="获取任务全部持久化结果",
)
async def get_task_results(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> TaskResultsResponse:
    """一次性返回任务的所有已持久化数据。

    包含：`transcript`（转写）、`evaluation`（评分摘要）、`compliance`（合规报告）。
    各字段在对应任务完成前为 `null`。
    `has_video`、`keyframe_count`、`ocr_text_count`、`visual_event_count`
    反映视觉扫描的完成情况，可用于判断是否需要提交合规审核。
    """
    persistence = store.persistence

    if not persistence.has_file(task_id, "meta.json"):
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

    transcript = None
    transcript_data = persistence.load_json(task_id, "transcript.json")
    if transcript_data:
        transcript = TranscriptResponse.model_validate(transcript_data)

    evaluation = None
    eval_data = persistence.load_json(task_id, "evaluation.json")
    if eval_data:
        evaluation = EvaluationResult.model_validate(eval_data)

    compliance = None
    compliance_data = persistence.load_json(task_id, "compliance.json")
    if compliance_data:
        compliance = ComplianceResponse.model_validate(compliance_data)

    has_audio = persistence.find_audio(task_id) is not None
    has_video = persistence.find_video(task_id) is not None
    has_synthesis = (persistence.path_of(task_id) / "synthesis.mp3").exists()
    keyframe_count = persistence.count_frames(task_id)

    ocr_data = persistence.load_json(task_id, "ocr_results.json")
    ocr_text_count = len(ocr_data) if isinstance(ocr_data, list) else 0

    events_data = persistence.load_json(task_id, "visual_events.json")
    visual_event_count = len(events_data) if isinstance(events_data, list) else 0

    return TaskResultsResponse(
        task_id=task_id,
        transcript=transcript,
        evaluation=evaluation,
        compliance=compliance,
        has_audio=has_audio,
        has_video=has_video,
        has_synthesis=has_synthesis,
        keyframe_count=keyframe_count,
        ocr_text_count=ocr_text_count,
        visual_event_count=visual_event_count,
    )


@router.patch(
    "/tasks/{task_id}/transcript",
    response_model=TranscriptUpdateResponse,
    tags=["任务管理"],
    summary="人工修订转写文本",
)
async def edit_transcript(
    task_id: str,
    body: TranscriptEditRequest,
    store: TaskStore = Depends(get_task_store),
) -> TranscriptUpdateResponse:
    """按句段下标批量修订 `text_corrected` 并持久化（原始 `text` 不变）。

    仅已完成的任务可修订；越界下标与内容未变化的句段会被忽略，
    `updated` 为实际变更条数。已生成的纪要与合规报告不会自动重算。
    """
    edits = {e.index: e.text_corrected for e in body.edits}
    return TranscriptUpdateResponse(updated=store.edit_transcript(task_id, edits))


@router.patch(
    "/tasks/{task_id}/speakers",
    response_model=TranscriptUpdateResponse,
    tags=["任务管理"],
    summary="重命名或合并说话人",
)
async def rename_speakers(
    task_id: str,
    body: SpeakerRenameRequest,
    store: TaskStore = Depends(get_task_store),
) -> TranscriptUpdateResponse:
    """按 `{原名: 新名}` 重写转写中的说话人标签并持久化。

    多个原名映射到同一新名即合并说话人。`updated` 为受影响的句段数。
    """
    return TranscriptUpdateResponse(updated=store.rename_speakers(task_id, body.renames))


@router.post(
    "/tasks/{task_id}/cancel",
    status_code=202,
    tags=["任务管理"],
    summary="取消运行中的任务",
)
async def cancel_task(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> dict:
    """取消排队中或处于 LLM 阶段（纠错 / 纪要 / 合规审核）的任务，任务将标记为失败（已取消）。

    ASR 推理与视觉扫描运行在线程中无法安全中断，此阶段返回 409，请等待其完成后再取消。
    """
    store.cancel_task(task_id)
    return {"ok": True}


@router.get(
    "/tasks/{task_id}/media",
    tags=["任务管理"],
    summary="下载原始媒体文件",
)
async def get_task_media(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """返回任务对应的原始上传文件（音频或视频）。

    优先返回视频；无视频则返回音频。生命周期清理（24 小时）后文件将不再存在，
    此时返回 404。
    """
    persistence = store.persistence

    video_path = persistence.find_video(task_id)
    if video_path and video_path.exists():
        mime = mimetypes.guess_type(str(video_path))[0] or "video/mp4"
        return FileResponse(video_path, media_type=mime)

    audio_path = persistence.find_audio(task_id)
    if audio_path and audio_path.exists():
        mime = mimetypes.guess_type(str(audio_path))[0] or "audio/mpeg"
        return FileResponse(audio_path, media_type=mime)

    task = store.get(task_id)
    if task and task.audio_path:
        legacy = Path(task.audio_path)
        if legacy.exists():
            mime = mimetypes.guess_type(str(legacy))[0] or "audio/mpeg"
            return FileResponse(legacy, media_type=mime)

    raise HTTPException(status_code=404, detail="Media file not found")


@router.get(
    "/tasks/{task_id}/frames/{filename}",
    tags=["任务管理"],
    summary="下载指定关键帧图像",
)
async def get_task_frame(
    task_id: str,
    filename: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """返回视觉扫描提取的单张关键帧（JPEG）。

    `filename` 格式通常为 `frame_0001.jpg`，可从 `keyframe_count` 推算范围，
    或通过合规报告中的 `evidence_url` 字段直接获取完整路径。
    """
    if not _SAFE_FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=422, detail="Invalid filename")
    frames_path = store.persistence.path_of(task_id) / "frames" / filename
    # is_file 而不是 exists：filename 允许包含 "."，".." 会命中目录并让 FileResponse 抛 500
    if not frames_path.is_file():
        raise HTTPException(status_code=404, detail="Frame not found")
    mime = mimetypes.guess_type(str(frames_path))[0] or "image/jpeg"
    return FileResponse(frames_path, media_type=mime)
