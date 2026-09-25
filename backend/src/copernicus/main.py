import asyncio
import logging
import os
from contextlib import asynccontextmanager

# 修复 Windows 下 joblib/loky 物理核心检测问题 (说话人分离聚类时触发)
# 必须在 joblib 导入前设置，禁用物理核心检测
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 8))
# setdefault：运维可在 systemd/环境中下调线程数，避免多核机器上 OpenMP 空转自旋耗电
os.environ.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 8))
# 必须在 CUDA 首次初始化前设置，允许分配器跨非连续内存页组合大块分配，消除碎片化 OOM
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
# 统一模型目录：必须在 modelscope / funasr 导入前设置，否则 ModelScope 的下载缓存路径会错误
# 优先使用 OS 环境变量（生产部署可覆盖），默认跟随 MODELS_DIR 配置（models/funasr/）
from copernicus.config import Settings, settings

os.environ.setdefault("MODELSCOPE_CACHE", str(settings.funasr_cache_dir.resolve()))

from copernicus.logging_setup import setup_logging_from_environment

setup_logging_from_environment()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html

from copernicus.error_handlers import register_error_handlers
from copernicus.request_context import REQUEST_ID_HEADER, RequestIdMiddleware
from copernicus.services.audio import AudioService
from copernicus.services.asr import ASRService
from copernicus.services.lifecycle import LifecycleService
from copernicus.services.llm import LLMClient, create_llm_client
from copernicus.services.corrector import CorrectorService
from copernicus.services.text_corrector import TextCorrectorService
from copernicus.services.hotword_replacer import HotwordReplacerService
from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.face_detector import FaceDetectorService
from copernicus.services.model_manager import ModelManager
from copernicus.services.ocr import OCRService
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_store import TaskStore
from copernicus.services.template_manager import TemplateManager
from copernicus.services.upload_session import UploadSessionService
from copernicus.routers import compliance, task, transcription, evaluation, upload
from copernicus.routers import synthesis as synthesis_router
import copernicus.services.tts as tts_service
from copernicus.services.preflight import run_preflight

logger = logging.getLogger(__name__)


async def _init_app_services(app: FastAPI, settings: Settings, llm_client: LLMClient) -> asyncio.Task:
    """构造并注册所有服务到 app.state，返回后台任务句柄。"""
    # 基础依赖层
    app.state.template_manager = TemplateManager(settings.templates_dir)
    audio_service    = AudioService(settings.audio_enhance)
    asr_service      = ASRService(settings)
    text_corrector   = TextCorrectorService(settings)
    hotword_replacer = HotwordReplacerService(settings)
    corrector_service = CorrectorService(llm_client, settings, text_corrector, hotword_replacer=hotword_replacer)
    persistence = PersistenceService(settings.upload_dir)
    app.state.upload_session = UploadSessionService(settings.upload_dir)
    ocr_service   = OCRService(settings) if settings.ocr_enabled else None
    face_detector = FaceDetectorService(settings) if settings.face_detect_enabled else None

    # 模型热插拔管理
    model_manager = ModelManager()
    model_manager.register_loader(
        "asr",
        loader=lambda: (asr_service.reload(), asr_service)[1],
        unloader=lambda _: asr_service.unload_weights(),
        vram_estimate_gb=4.5,
    )
    model_manager.mark_loaded("asr", asr_service)
    model_manager.register_loader(
        "tts",
        loader=lambda: tts_service.load_chattts(settings.chattts_model_dir),
        unloader=tts_service.unload_chattts,
        vram_estimate_gb=settings.tts_vram_estimate_gb,
    )
    app.state.model_manager = model_manager

    # 管道层
    app.state.pipeline = PipelineService(
        audio_service=audio_service,
        asr_service=asr_service,
        corrector_service=corrector_service,
        confidence_threshold=settings.confidence_threshold,
        chunk_size=settings.correction_chunk_size,
        run_merge_gap=settings.confidence_run_merge_gap,
        pre_merge_gap_ms=settings.pre_merge_gap_ms,
        hotword_replacer=hotword_replacer,
        settings=settings,
        persistence=persistence,
        model_manager=model_manager,
        ocr_service=ocr_service,
        face_detector=face_detector,
    )

    # LLM 衍生服务
    app.state.llm_client = llm_client
    app.state.evaluator  = EvaluatorService(llm_client, settings)
    app.state.compliance = ComplianceService(llm_client, settings)

    # 任务存储与恢复
    app.state.task_store = TaskStore(
        pipeline=app.state.pipeline,
        persistence=persistence,
        settings=settings,
        evaluator=app.state.evaluator,
        compliance=app.state.compliance,
        model_manager=model_manager,
        template_manager=app.state.template_manager,
    )
    app.state.task_store.restore_from_disk()

    # 后台定时清理：过期媒体、失败任务、中断上传与存储配额
    lifecycle = LifecycleService(
        settings.upload_dir, settings.media_retention_hours, settings.max_storage_gb
    )
    return asyncio.create_task(lifecycle.run_periodic())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Copernicus service ...")
    await run_preflight(settings)
    llm_client = create_llm_client(settings)
    lifecycle_task: asyncio.Task | None = None
    try:
        lifecycle_task = await _init_app_services(app, settings, llm_client)
        logger.info("Copernicus service ready.")
        yield
    finally:
        logger.info("Shutting down Copernicus service ...")
        task_store = getattr(app.state, "task_store", None)
        if task_store is not None:
            await task_store.cancel_all()
        if lifecycle_task is not None:
            lifecycle_task.cancel()
            await asyncio.gather(lifecycle_task, return_exceptions=True)
        await llm_client.close()


_OPENAPI_TAGS = [
    {
        "name": "存储层",
        "description": (
            "分片上传与断点续传。以文件 SHA-256 为唯一标识，最大 500 MB。"
            "上传完成后自动触发标准纪要任务。"
        ),
    },
    {
        "name": "基础 AI",
        "description": (
            "ASR 转写 + 文字纠错 + 智能摘要（One-Pass，显存占用 ≤ 12 GB）。"
            "覆盖 90% 的日常纪要场景。"
        ),
    },
    {
        "name": "高阶 AI",
        "description": (
            "OCR 视觉扫描 + YOLO 行为检测 + CoT 合规推理。"
            "针对 10% 高风险场景，执行前建议先完成基础 AI 转写。"
        ),
    },
    {
        "name": "任务管理",
        "description": (
            "通用任务轮询、结果读取与媒体文件获取。"
            "所有异步任务（基础 AI / 高阶 AI）均通过此入口查询状态。"
        ),
    },
    {
        "name": "音频重塑",
        "description": (
            "Phase 4：基于 CosyVoice 2.0 将转写结果合成为多说话人有声对话（MP3）。"
            "合成前需独占显存，ASR/LLM 模型将被自动卸载。"
        ),
    },
    {
        "name": "系统",
        "description": "健康检查、VRAM 水位监控与纪要模板管理。",
    },
]

_NPMMIRROR = "https://registry.npmmirror.com/swagger-ui-dist/5/files"

app = FastAPI(
    title="Copernicus",
    description="""\
三阶段多模态音视频合规审计平台，针对 RTX 5080 16 GB 显存优化。

| 层级 | 主入口 | 适用场景 |
|---|---|---|
| **存储层** | `PATCH /api/v1/uploads/{hash}` | 大文件分片上传 |
| **基础 AI** | `POST /api/v1/tasks/standard_minutes` | 转写 + 纠错 + 摘要 |
| **高阶 AI** | `POST /api/v1/tasks/compliance_audit` | 视觉 + 合规推理 |

所有异步任务提交后返回 `task_id`，通过 `GET /api/v1/tasks/{task_id}` 轮询状态，\
通过 `GET /api/v1/tasks/{task_id}/results` 一次性获取全部结果。
""",
    version="1.1.0",
    lifespan=lifespan,
    openapi_tags=_OPENAPI_TAGS,
    docs_url=None,
)


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title,
        swagger_js_url=f"{_NPMMIRROR}/swagger-ui-bundle.js",
        swagger_css_url=f"{_NPMMIRROR}/swagger-ui.css",
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)
# 后添加的中间件位于外层：最外层分配 request id，CORS 预检等所有请求都能带上
app.add_middleware(RequestIdMiddleware)

app.include_router(transcription.router)
app.include_router(task.router)
app.include_router(upload.router)
app.include_router(evaluation.router)
app.include_router(compliance.router)
app.include_router(synthesis_router.router)

register_error_handlers(app)
