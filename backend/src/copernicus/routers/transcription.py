from fastapi import APIRouter, Depends

from copernicus.config import settings
from copernicus.dependencies import get_model_manager, get_pipeline
from copernicus.schemas.transcription import HealthResponse, VramStatus
from copernicus.services.model_manager import ModelManager
from copernicus.services.pipeline import PipelineService

router = APIRouter(prefix="/api/v1", tags=["系统"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="服务健康检查",
)
async def health(
    pipeline: PipelineService = Depends(get_pipeline),
    model_manager: ModelManager | None = Depends(get_model_manager),
) -> HealthResponse:
    """返回 ASR 模型加载状态、LLM 可达性和 VRAM 水位。

    `asr_loaded` 为 `false` 表示 ASR 权重已被合规审计任务卸载，
    下一次转写任务将自动重新加载。`vram.estimated_used_gb` 仅统计
    通过 ModelManager 管理的模型，Ollama 进程占用需另行查看。
    """
    asr_loaded = pipeline._asr is not None and pipeline._asr.is_loaded()
    llm_reachable = await pipeline._corrector.is_reachable()

    vram: VramStatus | None = None
    if model_manager is not None:
        vram = VramStatus(
            loaded_models=model_manager.loaded_models,
            estimated_used_gb=model_manager.estimated_vram_gb,
            budget_gb=settings.vram_budget_gb,
        )
    return HealthResponse(asr_loaded=asr_loaded, llm_reachable=llm_reachable, vram=vram)
