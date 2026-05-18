import hashlib
import mimetypes
from pathlib import Path
from typing import NamedTuple

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from copernicus.config import settings
from copernicus.dependencies import get_task_store
from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResult
from copernicus.schemas.task import (
    TaskStatus,
    TaskStatusResponse,
    TaskSubmitResponse,
    TaskResultsResponse,
)
from copernicus.schemas.transcription import TranscriptResponse
from copernicus.services.task_store import TaskStore
from copernicus.utils.request import parse_hotwords

# 不设置 router 级 tags，各路由按逻辑层单独标注
router = APIRouter(prefix="/api/v1")


class _UploadResult(NamedTuple):
    audio_bytes: bytes
    file_hash: str
    hotwords: list[str]
    filename: str
    existing_response: TaskSubmitResponse | None


async def _read_upload(
    file: UploadFile,
    hotwords_str: str | None,
    store: TaskStore,
) -> _UploadResult:
    """读取并校验上传文件；文件已存在时在 existing_response 中返回缓存响应。"""
    audio_bytes = await file.read()
    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")
    file_hash = hashlib.sha256(audio_bytes).hexdigest()
    existing_id = store.lookup_by_hash(file_hash)
    if existing_id:
        existing_task = store.get(existing_id)
        existing_status = existing_task.status if existing_task else TaskStatus.COMPLETED
        existing_resp = TaskSubmitResponse(task_id=existing_id, status=existing_status, existing=True)
        return _UploadResult(b"", file_hash, [], "", existing_resp)
    try:
        hw = parse_hotwords(hotwords_str)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _UploadResult(audio_bytes, file_hash, hw, file.filename or "upload.bin", None)


def _persist_task_media(
    store: TaskStore,
    task_id: str,
    audio_bytes: bytes,
    filename: str,
    file_hash: str,
) -> None:
    """保存上传媒体文件和 meta.json，并更新任务的 audio_path。"""
    path = store.persistence.persist_media(
        task_id, filename, file_hash, audio_bytes, settings.video_extensions_set
    )
    task = store.get(task_id)
    if task:
        task.audio_path = str(path)


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
    upload = await _read_upload(file, hotwords, store)
    if upload.existing_response:
        return upload.existing_response
    task_id = store.submit_standard_minutes(
        upload.audio_bytes, upload.filename, upload.hotwords,
        file_hash=upload.file_hash,
        visual_scan=visual_scan,
        generate_summary=generate_summary,
        template_id=template_id,
    )
    _persist_task_media(store, task_id, upload.audio_bytes, upload.filename, upload.file_hash)
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
    upload = await _read_upload(file, hotwords, store)
    if upload.existing_response:
        return upload.existing_response
    task_id = store.submit_transcript(
        upload.audio_bytes, upload.filename, upload.hotwords,
        file_hash=upload.file_hash,
        visual_scan=visual_scan,
    )
    _persist_task_media(store, task_id, upload.audio_bytes, upload.filename, upload.file_hash)
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
    try:
        store.rerun_transcript(task_id, hw)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)



# ---------------------------------------------------------------------------
# 任务管理 — 查询与媒体
# ---------------------------------------------------------------------------

@router.delete(
    "/tasks/{task_id}",
    status_code=204,
    tags=["任务管理"],
    summary="作废任务缓存（不删除磁盘文件）",
)
async def invalidate_task(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> None:
    """从内存和哈希索引中移除指定任务的缓存记录。

    清除后，使用相同文件重新调用 `POST /api/v1/tasks/standard_minutes`
    将触发完整流水线重新处理，而不是返回 `existing=true`。
    磁盘上的原始媒体和结果文件不会被删除。
    """
    found = store.invalidate_task(task_id)
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
    has_synthesis = (persistence.task_dir(task_id) / "synthesis.mp3").exists()
    frames_path = persistence.task_dir(task_id) / "frames"
    keyframe_count = len(list(frames_path.glob("*"))) if frames_path.is_dir() else 0

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
    frames_path = store.persistence.task_dir(task_id) / "frames" / filename
    if not frames_path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")
    mime = mimetypes.guess_type(str(frames_path))[0] or "image/jpeg"
    return FileResponse(frames_path, media_type=mime)
