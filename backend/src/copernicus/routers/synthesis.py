import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from copernicus.dependencies import get_synthesis_service, get_task_store
from copernicus.schemas.synthesis import SynthesisRequest, SynthesisStatusResponse
from copernicus.schemas.transcription import TranscriptResponse
from copernicus.services.synthesis import SynthesisService
from copernicus.services.task_store import TaskStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["音频重塑"])


@router.post(
    "/tasks/{task_id}/synthesize",
    response_model=SynthesisStatusResponse,
    status_code=202,
    tags=["音频重塑"],
    summary="提交多说话人对话音频合成任务（异步）",
)
async def synthesize_task_audio(
    task_id: str,
    request: SynthesisRequest | None = None,
    store: TaskStore = Depends(get_task_store),
    synthesis: SynthesisService | None = Depends(get_synthesis_service),
) -> SynthesisStatusResponse:
    """提交合成任务，立即返回 202；通过 GET /tasks/{task_id}/synthesis/status 轮询进度。

    - 不同说话人自动分配不同音色（可通过 `voice_map` 覆盖）。
    - 合成期间 ASR 模型自动卸载，独占显存；合成结束后 TTS 立即卸载。
    - 同一任务重复提交时若合成正在进行则返回 409。
    """
    if synthesis is None:
        raise HTTPException(status_code=503, detail="ModelManager not available")

    if store.has_active_llm_tasks():
        raise HTTPException(status_code=503, detail="LLM task in progress, retry later.")

    transcript_data = store.persistence.load_json(task_id, "transcript.json")
    if transcript_data is None:
        raise HTTPException(status_code=404, detail="Transcript not found for task")

    transcript = TranscriptResponse.model_validate(transcript_data)
    if not transcript.transcript:
        raise HTTPException(status_code=422, detail="Transcript is empty")

    await synthesis.start(task_id, transcript, request.voice_map if request else None)
    return SynthesisStatusResponse(status="running")


@router.get(
    "/tasks/{task_id}/synthesis/status",
    response_model=SynthesisStatusResponse,
    tags=["音频重塑"],
    summary="查询合成任务状态",
)
async def get_synthesis_status(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> SynthesisStatusResponse:
    """轮询合成进度。status 取值：running | completed | failed。"""
    audio_url = f"/api/v1/tasks/{task_id}/synthesis"

    job = store.get_synthesis_job(task_id)
    if job is not None:
        if job.status == "completed":
            return SynthesisStatusResponse(
                status="completed",
                audio_url=audio_url,
                duration_ms=job.duration_ms,
                synthesis_time_ms=job.synthesis_time_ms,
            )
        if job.status == "failed":
            return SynthesisStatusResponse(status="failed", error=job.error)
        return SynthesisStatusResponse(status="running")

    # 服务重启后内存 job 丢失 — 从磁盘恢复
    result = store.persistence.load_json(task_id, "synthesis_result.json")
    if result:
        return SynthesisStatusResponse(
            status="completed",
            audio_url=audio_url,
            duration_ms=result.get("duration_ms"),
            synthesis_time_ms=result.get("synthesis_time_ms"),
        )

    mp3_path = store.persistence.path_of(task_id) / "synthesis.mp3"
    if mp3_path.exists():
        return SynthesisStatusResponse(status="completed", audio_url=audio_url)

    raise HTTPException(status_code=404, detail="No synthesis found for this task")


@router.get(
    "/tasks/{task_id}/synthesis",
    tags=["音频重塑"],
    summary="下载已合成的对话音频",
)
async def get_synthesis_audio(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """返回 `POST /synthesize` 生成的 MP3 文件。生命周期同原始媒体（24 小时后自动清理）。"""
    path = store.persistence.path_of(task_id) / "synthesis.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Synthesis audio not found. Call POST /synthesize first.")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{task_id}_synthesis.mp3")
