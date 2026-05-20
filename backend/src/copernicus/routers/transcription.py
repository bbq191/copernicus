from fastapi import APIRouter, Depends, Response

from copernicus.config import settings
from copernicus.dependencies import get_model_manager, get_pipeline, get_task_store
from copernicus.schemas.transcription import (
    ComponentStatus,
    HealthResponse,
    TaskStats,
    VramStatus,
)
from copernicus.services.model_manager import ModelManager
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1", tags=["系统"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="服务健康检查",
)
async def health(
    response: Response,
    pipeline: PipelineService = Depends(get_pipeline),
    model_manager: ModelManager | None = Depends(get_model_manager),
    store: TaskStore = Depends(get_task_store),
) -> HealthResponse:
    """返回服务整体健康状态、各组件状态及任务队列统计。

    `status` 取值：
    - `healthy`: ASR 已加载且 LLM 可达
    - `degraded`: ASR 未在 VRAM（将自动重载）或 LLM 暂不可达
    - `unhealthy`: ASR 服务未配置，503 响应

    `vram.estimated_used_gb` 仅统计通过 ModelManager 管理的模型，Ollama 进程占用需另行查看。
    """
    # ASR
    if pipeline._asr is None:
        asr = ComponentStatus(status="down", detail="ASR service not configured")
    elif pipeline._asr.is_loaded():
        asr = ComponentStatus(status="ok")
    else:
        asr = ComponentStatus(status="degraded", detail="weights unloaded, will reload on next transcription")

    # LLM
    llm_ok = await pipeline._corrector.is_reachable()
    llm = ComponentStatus(status="ok" if llm_ok else "down")

    # TTS
    tts: ComponentStatus | None = None
    if model_manager is not None:
        if "tts" in model_manager.loaded_models:
            tts = ComponentStatus(status="ok")
        elif settings.chattts_model_dir.exists():
            tts = ComponentStatus(status="degraded", detail="model files present, not loaded (loads on demand)")
        else:
            tts = ComponentStatus(status="down", detail=f"model directory not found: {settings.chattts_model_dir}")

    # Overall status
    if asr.status == "down":
        overall = "unhealthy"
    elif asr.status == "degraded" or llm.status == "down" or (tts is not None and tts.status == "down"):
        overall = "degraded"
    else:
        overall = "healthy"

    if overall == "unhealthy":
        response.status_code = 503

    # VRAM
    vram: VramStatus | None = None
    if model_manager is not None:
        vram = VramStatus(
            loaded_models=model_manager.loaded_models,
            estimated_used_gb=model_manager.estimated_vram_gb,
            budget_gb=settings.vram_budget_gb,
        )

    raw = store.get_task_stats()
    tasks = TaskStats(
        active=raw["active"],
        completed=raw["completed"],
        failed=raw["failed"],
        synthesis_running=raw["synthesis_running"],
    )

    return HealthResponse(status=overall, asr=asr, llm=llm, tts=tts, tasks=tasks, vram=vram)
