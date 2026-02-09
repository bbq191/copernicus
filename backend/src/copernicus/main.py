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
from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
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

    audio_service = AudioService(settings)
    asr_service = ASRService(settings)
    text_corrector = TextCorrectorService(settings)
    corrector_service = CorrectorService(llm_client, settings, text_corrector)

    app.state.pipeline = PipelineService(
        audio_service=audio_service,
        asr_service=asr_service,
        corrector_service=corrector_service,
        confidence_threshold=settings.confidence_threshold,
        chunk_size=settings.correction_chunk_size,
        run_merge_gap=settings.confidence_run_merge_gap,
        pre_merge_gap_ms=settings.pre_merge_gap_ms,
        hotwords_file=settings.hotwords_file,
    )
    app.state.evaluator = EvaluatorService(llm_client, settings)
    app.state.compliance = ComplianceService(llm_client, settings)
    persistence = PersistenceService(settings.upload_dir)
    app.state.task_store = TaskStore(
        pipeline=app.state.pipeline,
        persistence=persistence,
        evaluator=app.state.evaluator,
        compliance=app.state.compliance,
    )
    app.state.task_store.restore_from_disk()

    logger.info("Copernicus service ready.")
    yield

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
    allow_origins=["http://localhost:3000"],
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
