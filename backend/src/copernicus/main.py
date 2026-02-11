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
from copernicus.services.llm import OllamaClient
from copernicus.services.corrector import CorrectorService
from copernicus.services.text_corrector import TextCorrectorService
from copernicus.services.hotword_replacer import HotwordReplacerService
from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.face_detector import FaceDetectorService
from copernicus.services.ocr import OCRService
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_store import TaskStore
from copernicus.routers import compliance, task, transcription, evaluation

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load ASR model on startup, release on shutdown."""
    logger.info("Starting Copernicus service ...")

    llm_client = OllamaClient(settings)
    try:
        audio_service = AudioService(settings)
        asr_service = ASRService(settings)
        text_corrector = TextCorrectorService(settings)
        hotword_replacer = HotwordReplacerService(settings)
        corrector_service = CorrectorService(
            llm_client, settings, text_corrector, hotword_replacer=hotword_replacer
        )

        persistence = PersistenceService(settings.upload_dir)
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
        app.state.task_store = TaskStore(
            pipeline=app.state.pipeline,
            persistence=persistence,
            settings=settings,
            evaluator=app.state.evaluator,
            compliance=app.state.compliance,
        )
        app.state.task_store.restore_from_disk()

        logger.info("Copernicus service ready.")
        yield
    finally:
        logger.info("Shutting down Copernicus service ...")
        await llm_client.close()


app = FastAPI(
    title="Copernicus",
    description="ASR + NLP text correction service",
    version="0.1.0",
    lifespan=lifespan,
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
app.include_router(evaluation.router)
app.include_router(compliance.router)


@app.exception_handler(CopernicusError)
async def copernicus_error_handler(request: Request, exc: CopernicusError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
