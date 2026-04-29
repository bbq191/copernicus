import asyncio
import logging
import logging.config
import os
from contextlib import asynccontextmanager

# 修复 Windows 下 joblib/loky 物理核心检测问题 (说话人分离聚类时触发)
# 必须在 joblib 导入前设置，禁用物理核心检测
os.environ["LOKY_MAX_CPU_COUNT"] = str(os.cpu_count() or 8)
os.environ["OMP_NUM_THREADS"] = str(os.cpu_count() or 8)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from copernicus.config import settings
from copernicus.exceptions import CopernicusError
from copernicus.services.audio import AudioService
from copernicus.services.asr import ASRService
from copernicus.services.lifecycle import LifecycleService
from copernicus.services.llm import OllamaClient
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时加载 ASR 模型，关闭时释放资源。"""
    logger.info("Starting Copernicus service ...")

    llm_client = OllamaClient(settings)
    try:
        app.state.template_manager = TemplateManager(settings.templates_dir)

        audio_service = AudioService(settings)
        asr_service = ASRService(settings)
        text_corrector = TextCorrectorService(settings)
        hotword_replacer = HotwordReplacerService(settings)
        corrector_service = CorrectorService(
            llm_client, settings, text_corrector, hotword_replacer=hotword_replacer
        )

        persistence = PersistenceService(settings.upload_dir)
        app.state.upload_session = UploadSessionService(settings.upload_dir)
        ocr_service = OCRService(settings) if settings.ocr_enabled else None
        face_detector = FaceDetectorService(settings) if settings.face_detect_enabled else None
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
            ocr_service=ocr_service,
            face_detector=face_detector,
        )
        app.state.evaluator = EvaluatorService(llm_client, settings)
        app.state.compliance = ComplianceService(llm_client, settings)

        # ModelManager：注册 ASR 热插拔加载器
        model_manager = ModelManager()
        model_manager.register_loader(
            "asr",
            loader=lambda: (asr_service.reload(), asr_service)[1],
            unloader=lambda _: asr_service.unload_weights(),
            vram_estimate_gb=2.0,
        )
        model_manager.mark_loaded("asr", asr_service)  # ASRService.__init__ 已加载
        app.state.model_manager = model_manager

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

        # 后台定时清理过期原始媒体文件
        lifecycle = LifecycleService(settings.upload_dir, settings.media_retention_hours)
        asyncio.create_task(lifecycle.run_periodic())

        logger.info("Copernicus service ready.")
        yield
    finally:
        logger.info("Shutting down Copernicus service ...")
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
        "name": "系统",
        "description": "健康检查、VRAM 水位监控与纪要模板管理。",
    },
]

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
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transcription.router)
app.include_router(task.router)
app.include_router(upload.router)
app.include_router(evaluation.router)
app.include_router(compliance.router)


@app.exception_handler(CopernicusError)
async def copernicus_error_handler(request: Request, exc: CopernicusError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
