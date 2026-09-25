"""Prometheus 抓取端点。

不在 /api/v1 之下，也未被 Nginx 模板转发：只有能直连后端端口（默认仅本机回环）的抓取器可以访问。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from copernicus import metrics
from copernicus.dependencies import get_model_manager, get_task_store
from copernicus.services.model_manager import ModelManager
from copernicus.services.task_store import TaskStore

router = APIRouter(tags=["系统"])


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus 指标")
async def scrape(
    store: TaskStore = Depends(get_task_store),
    model_manager: ModelManager | None = Depends(get_model_manager),
) -> PlainTextResponse:
    """请求与任务的累计指标，加上抓取时刻的任务分布与模型驻留情况。"""
    gauges = [
        metrics.Gauge(
            "copernicus_tasks",
            "内存中各状态的任务数",
            lambda: [({"status": s}, n) for s, n in store.count_by_status().items()],
        ),
        metrics.Gauge(
            "copernicus_synthesis_running",
            "正在进行的音频合成数",
            lambda: [({}, store.get_task_stats()["synthesis_running"])],
        ),
    ]
    if model_manager is not None:
        gauges.append(
            metrics.Gauge(
                "copernicus_model_loaded",
                "模型是否驻留显存（1 是，0 否）",
                lambda: [({"model": m}, 1) for m in model_manager.loaded_models],
            )
        )
        gauges.append(
            metrics.Gauge(
                "copernicus_vram_estimated_gb",
                "受 ModelManager 管理的模型估算显存（不含 Ollama）",
                lambda: [({}, model_manager.estimated_vram_gb)],
            )
        )
    return PlainTextResponse(metrics.registry.render(gauges), media_type=metrics.CONTENT_TYPE)
